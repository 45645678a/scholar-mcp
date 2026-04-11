"""工作区代码分析 → 论文推荐

扫描工作区文件，提取关键词（import 库名、算法名、注释中的学术术语），
然后通过 Semantic Scholar 搜索推荐相关论文。
"""

import os
import re
from collections import Counter
from searcher import search_papers
from logger import get_logger

log = get_logger("recommender")

# 科学库 → 学术领域关键词映射
LIBRARY_TO_KEYWORDS = {
    # Python 科学计算
    "numpy": "numerical computing",
    "scipy": "scientific computing optimization",
    "pandas": "data analysis",
    "matplotlib": "data visualization",
    "seaborn": "statistical visualization",
    "plotly": "interactive visualization",
    # 机器学习 / 深度学习
    "sklearn": "machine learning",
    "scikit-learn": "machine learning",
    "tensorflow": "deep learning neural network",
    "keras": "deep learning",
    "torch": "deep learning PyTorch",
    "pytorch": "deep learning",
    "transformers": "transformer language model NLP",
    "huggingface": "pretrained language model",
    "jax": "differentiable programming",
    "flax": "neural network JAX",
    "xgboost": "gradient boosting",
    "lightgbm": "gradient boosting",
    "catboost": "gradient boosting categorical features",
    # 计算机视觉
    "cv2": "computer vision image processing",
    "opencv": "computer vision",
    "torchvision": "computer vision deep learning",
    "detectron2": "object detection segmentation",
    "ultralytics": "YOLO object detection",
    "mediapipe": "pose estimation hand tracking",
    # NLP
    "nltk": "natural language processing",
    "spacy": "natural language processing",
    "gensim": "topic modeling word embedding",
    "fasttext": "word embedding text classification",
    # 信号处理
    "librosa": "audio signal processing",
    "soundfile": "audio processing",
    "pywt": "wavelet transform signal processing",
    # 优化
    "pyomo": "mathematical optimization",
    "cvxpy": "convex optimization",
    "optuna": "hyperparameter optimization",
    "pymoo": "multi-objective optimization evolutionary algorithm",
    "deap": "evolutionary algorithm genetic programming",
    "platypus": "multi-objective optimization",
    # 物理 / 仿真
    "fenics": "finite element method",
    "fipy": "finite volume partial differential equation",
    "pyvista": "3D visualization mesh",
    "gmsh": "mesh generation finite element",
    "comsol": "multiphysics simulation",
    "ansys": "finite element analysis",
    "openfoam": "computational fluid dynamics",
    # 电磁
    "magpylib": "magnetic field simulation",
    "femm": "finite element magnetics",
    "meep": "electromagnetic simulation FDTD",
    # 量子
    "qiskit": "quantum computing",
    "cirq": "quantum computing",
    "pennylane": "quantum machine learning",
    # 生物信息
    "biopython": "bioinformatics",
    "scanpy": "single-cell genomics",
    "rdkit": "cheminformatics molecular",
    # 地理
    "geopandas": "geospatial analysis",
    "rasterio": "remote sensing",
    "folium": "geographic visualization",
    # 控制
    "control": "control systems",
    "python-control": "control systems feedback",
    # 统计
    "statsmodels": "statistical modeling",
    "pymc": "Bayesian statistics probabilistic programming",
    "arviz": "Bayesian analysis visualization",
    # 机器人
    "rospy": "robotics ROS",
    "rclpy": "robotics ROS2",
    "pybullet": "physics simulation robotics",
    "mujoco": "physics simulation robotics",
    # Web / API
    "fastapi": "web API",
    "flask": "web application",
    "django": "web framework",
    "streamlit": "data application dashboard",
    "gradio": "machine learning demo interface",
    # 半导体 / 材料科学
    "ase": "atomistic simulation materials science",
    "pymatgen": "materials science computational",
    "lammps": "molecular dynamics simulation",
    "vasp": "density functional theory DFT",
    "gpaw": "density functional theory electronic structure",
    "nexusformat": "neutron scattering X-ray",
    "semiconductor": "semiconductor physics",
    # 化学
    "openbabel": "cheminformatics molecular conversion",
    "pyscf": "quantum chemistry",
    "orca": "quantum chemistry computational",
    "gaussian": "quantum chemistry DFT",
    # 天文
    "astropy": "astronomy astrophysics",
    "sunpy": "solar physics heliophysics",
    "lightkurve": "exoplanet transit photometry",
    # 强化学习
    "gymnasium": "reinforcement learning environment",
    "stable_baselines3": "reinforcement learning policy optimization",
    "ray": "distributed reinforcement learning",
    # 图神经网络
    "torch_geometric": "graph neural network",
    "dgl": "graph neural network deep learning",
    "networkx": "network analysis graph theory",
    # 生成式 AI
    "diffusers": "diffusion model image generation",
    "openai": "large language model GPT",
    "langchain": "large language model agent",
    "llamaindex": "retrieval augmented generation RAG",
    # 语音
    "whisper": "speech recognition automatic",
    "espnet": "speech recognition synthesis",
    "torchaudio": "audio deep learning",
}

# 文件扩展名 → 语言
SCAN_EXTENSIONS = {
    ".py": "python",
    ".ipynb": "python",
    ".r": "r",
    ".R": "r",
    ".m": "matlab",
    ".tex": "latex",
    ".bib": "bibtex",
    ".md": "markdown",
    ".rst": "markdown",
    ".js": "javascript",
    ".ts": "typescript",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".java": "java",
    ".jl": "julia",
}

# Python import 正则
PY_IMPORT_RE = re.compile(
    r"^\s*(?:import|from)\s+([\w.]+)", re.MULTILINE
)

# 注释中的学术关键词匹配
ACADEMIC_TERMS_RE = re.compile(
    r"\b(algorithm|optimization|neural network|deep learning|machine learning|"
    r"regression|classification|clustering|reinforcement learning|"
    r"gradient descent|convex|finite element|simulation|"
    r"Bayesian|Monte Carlo|PDE|ODE|eigenvalue|"
    r"transformer|attention mechanism|diffusion model|"
    r"CNN|RNN|LSTM|GAN|VAE|autoencoder|"
    r"coil design|magnetic field|impedance|sensor|"
    r"spectrum|transmittance|semiconductor|bandgap|"
    r"Pareto|multi-objective|NSGA|evolutionary|"
    r"molecular dynamics|density functional|first.principles|"
    r"photovoltaic|perovskite|thin.film|epitax|"
    r"retrieval.augmented|knowledge graph|embedding|"
    r"federated learning|contrastive learning|self.supervised|"
    r"graph neural|point cloud|3D reconstruction)\b",
    re.IGNORECASE,
)

# LaTeX 关键词
LATEX_KEYWORD_RE = re.compile(
    r"\\(?:title|section|subsection|chapter)\{([^}]+)\}", re.MULTILINE
)

# 跳过的目录名集合
_SKIP_DIRS = frozenset({
    "node_modules", "__pycache__", "venv", "env", ".venv",
    ".git", ".hg", ".svn", ".tox", ".mypy_cache",
    "dist", "build", "egg-info", ".eggs",
})

# 最大扫描目录深度
_MAX_SCAN_DEPTH = 8


def _should_skip_dir(dirname: str) -> bool:
    """检查是否应跳过目录（兼容 Windows 和 Unix）"""
    return dirname.startswith(".") or dirname in _SKIP_DIRS


def _scan_directory(workspace_path: str, max_files: int = 100) -> dict:
    """扫描工作区目录，收集代码特征"""
    imports = Counter()
    academic_terms = Counter()
    latex_titles = []
    file_count = 0

    base_depth = workspace_path.rstrip(os.sep).count(os.sep)

    for root, dirs, files in os.walk(workspace_path):
        # 检查深度限制
        current_depth = root.count(os.sep) - base_depth
        if current_depth >= _MAX_SCAN_DEPTH:
            dirs.clear()
            continue

        # 原地过滤跳过的目录（阻止 os.walk 进入）
        dirs[:] = [d for d in dirs if not _should_skip_dir(d)]

        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in SCAN_EXTENSIONS:
                continue

            file_count += 1
            if file_count > max_files:
                break

            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read(50_000)  # 最多读 50KB
            except (OSError, PermissionError):
                continue

            lang = SCAN_EXTENSIONS[ext]

            # Python imports
            if lang == "python":
                for m in PY_IMPORT_RE.finditer(content):
                    lib = m.group(1).split(".")[0]
                    imports[lib] += 1

            # 学术术语
            for m in ACADEMIC_TERMS_RE.finditer(content):
                academic_terms[m.group(1).lower()] += 1

            # LaTeX 标题
            if lang == "latex":
                for m in LATEX_KEYWORD_RE.finditer(content):
                    latex_titles.append(m.group(1))

        if file_count > max_files:
            break

    log.info("scanned %d files in %s", file_count, workspace_path)
    return {
        "imports": imports,
        "academic_terms": academic_terms,
        "latex_titles": latex_titles,
        "files_scanned": file_count,
    }


def _build_query(scan_result: dict, max_terms: int = 8) -> str:
    """从扫描结果构建搜索查询"""
    keywords = []

    # 1. 从 imports 映射学术关键词
    for lib, count in scan_result["imports"].most_common(20):
        if lib in LIBRARY_TO_KEYWORDS:
            keywords.append((LIBRARY_TO_KEYWORDS[lib], count * 2))

    # 2. 加入学术术语
    for term, count in scan_result["academic_terms"].most_common(10):
        keywords.append((term, count))

    # 3. LaTeX 标题（高权重）
    for title in scan_result["latex_titles"][:3]:
        keywords.append((title, 10))

    # 按权重排序取前 N
    keywords.sort(key=lambda x: x[1], reverse=True)
    unique = []
    seen = set()
    for kw, _ in keywords:
        for w in kw.split():
            if w.lower() not in seen:
                unique.append(w)
                seen.add(w.lower())
            if len(unique) >= max_terms:
                break
        if len(unique) >= max_terms:
            break

    return " ".join(unique)


def _build_queries(scan_result: dict, max_queries: int = 3) -> list[str]:
    """从扫描结果构建多个查询（覆盖不同代码信号维度）"""
    queries = []

    # 查询 1: 基于主要 import 库的学术方向
    lib_keywords = []
    for lib, count in scan_result["imports"].most_common(10):
        if lib in LIBRARY_TO_KEYWORDS:
            lib_keywords.append((LIBRARY_TO_KEYWORDS[lib], count * 2))
    if lib_keywords:
        lib_keywords.sort(key=lambda x: x[1], reverse=True)
        words = []
        seen = set()
        for kw, _ in lib_keywords[:5]:
            for w in kw.split():
                if w.lower() not in seen:
                    words.append(w)
                    seen.add(w.lower())
                if len(words) >= 8:
                    break
            if len(words) >= 8:
                break
        if words:
            queries.append(" ".join(words))

    # 查询 2: 基于代码中的学术术语
    if scan_result["academic_terms"]:
        terms = [t for t, _ in scan_result["academic_terms"].most_common(6)]
        if terms:
            queries.append(" ".join(terms))

    # 查询 3: 基于 LaTeX 标题（最精确）
    if scan_result["latex_titles"]:
        queries.append(scan_result["latex_titles"][0])

    # 去重
    unique = []
    seen = set()
    for q in queries:
        q_norm = q.lower().strip()
        if q_norm and q_norm not in seen:
            unique.append(q)
            seen.add(q_norm)

    # 如果以上都没有，退回到旧的单查询
    if not unique:
        fallback = _build_query(scan_result)
        if fallback:
            unique = [fallback]

    return unique[:max_queries]


def recommend_papers(workspace_path: str, top_n: int = 8) -> dict:
    """分析工作区代码，推荐相关论文（多查询策略）

    Args:
        workspace_path: 工作区根目录路径
        top_n: 返回推荐数量

    Returns:
        推荐结果字典
    """
    if not os.path.isdir(workspace_path):
        return {"success": False, "error": f"directory not found: {workspace_path}"}

    # 1. 扫描工作区
    scan = _scan_directory(workspace_path)
    if scan["files_scanned"] == 0:
        return {
            "success": False,
            "error": "no supported source files found in workspace",
        }

    # 2. 构建多个查询（覆盖不同代码信号）
    queries = _build_queries(scan)
    if not queries:
        return {
            "success": False,
            "error": "could not extract meaningful keywords from workspace",
        }

    log.info("recommend queries: %s", queries)

    # 3. 搜索论文（多查询合并）
    all_papers = []
    seen_dois = set()
    for q in queries:
        search_result = search_papers(q, rows=top_n)
        for paper in search_result.get("results", []):
            doi = paper.get("doi", "")
            if doi and doi in seen_dois:
                continue
            seen_dois.add(doi)
            all_papers.append(paper)

    # 按引用排序，取 top_n
    all_papers.sort(key=lambda x: x.get("cited_by", 0), reverse=True)
    all_papers = all_papers[:top_n]
    for i, p in enumerate(all_papers):
        p["index"] = i + 1

    # 4. 组装结果
    return {
        "success": True,
        "workspace": workspace_path,
        "files_scanned": scan["files_scanned"],
        "detected_libraries": dict(scan["imports"].most_common(10)),
        "detected_terms": dict(scan["academic_terms"].most_common(10)),
        "search_queries": queries,
        "recommended_papers": all_papers,
    }
