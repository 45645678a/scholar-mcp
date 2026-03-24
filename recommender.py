"""工作区代码分析 → 论文推荐

扫描工作区文件，提取关键词（import 库名、算法名、注释中的学术术语），
然后通过 Semantic Scholar 搜索推荐相关论文。
"""

import os
import re
from collections import Counter
from searcher import search_papers


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
    r"spectrum|transmittance|semiconductor|"
    r"Pareto|multi-objective|NSGA|evolutionary)\b",
    re.IGNORECASE,
)

# LaTeX 关键词
LATEX_KEYWORD_RE = re.compile(
    r"\\(?:title|section|subsection|chapter)\{([^}]+)\}", re.MULTILINE
)


def _scan_directory(workspace_path: str, max_files: int = 100) -> dict:
    """扫描工作区目录，收集代码特征"""
    imports = Counter()
    academic_terms = Counter()
    latex_titles = []
    file_count = 0

    for root, _dirs, files in os.walk(workspace_path):
        # 跳过隐藏目录和常见非代码目录
        parts = root.replace("\\", "/").split("/")
        if any(p.startswith(".") or p in ("node_modules", "__pycache__", "venv", "env", ".git") for p in parts):
            continue

        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in SCAN_EXTENSIONS:
                continue

            file_count += 1
            if file_count > max_files:
                break

            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read(50_000)  # 最多读 50KB
            except Exception:
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
        for word in kw.split():
            if word.lower() not in seen:
                unique.append(word)
                seen.add(word.lower())
            if len(unique) >= max_terms:
                break
        if len(unique) >= max_terms:
            break

    return " ".join(unique)


def recommend_papers(workspace_path: str, top_n: int = 8) -> dict:
    """分析工作区代码，推荐相关论文

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

    # 2. 构建查询
    query = _build_query(scan)
    if not query:
        return {
            "success": False,
            "error": "could not extract meaningful keywords from workspace",
        }

    # 3. 搜索论文
    search_result = search_papers(query, rows=top_n)

    # 4. 组装结果
    return {
        "success": True,
        "workspace": workspace_path,
        "files_scanned": scan["files_scanned"],
        "detected_libraries": dict(scan["imports"].most_common(10)),
        "detected_terms": dict(scan["academic_terms"].most_common(10)),
        "search_query": query,
        "recommended_papers": search_result.get("results", []),
    }
