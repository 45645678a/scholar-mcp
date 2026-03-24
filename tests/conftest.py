"""Shared fixtures for scholar-mcp tests."""
import pytest


@pytest.fixture
def sample_paper():
    """A standard paper dict for testing."""
    return {
        "title": "Attention Is All You Need",
        "authors": "Ashish Vaswani, Noam Shazeer",
        "journal": "NeurIPS",
        "year": "2017",
        "doi": "10.5555/3295222.3295349",
        "cited_by": 100000,
        "abstract": "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks.",
        "open_access_url": "https://arxiv.org/pdf/1706.03762",
        "source": "semantic_scholar",
    }


@pytest.fixture
def sample_paper_variant():
    """Same paper with slight title variation (for dedup testing)."""
    return {
        "title": "Attention is All You Need",  # lowercase 'is'
        "authors": "Vaswani et al.",
        "journal": "NIPS",
        "year": "2017",
        "doi": "10.5555/3295222.3295349",
        "cited_by": 95000,
        "abstract": "",
        "open_access_url": "",
        "source": "crossref",
    }


@pytest.fixture
def sample_paper_different():
    """A completely different paper."""
    return {
        "title": "BERT: Pre-training of Deep Bidirectional Transformers",
        "authors": "Jacob Devlin, Ming-Wei Chang",
        "journal": "NAACL",
        "year": "2019",
        "doi": "10.18653/v1/N19-1423",
        "cited_by": 80000,
        "abstract": "We introduce a new language representation model called BERT.",
        "open_access_url": "https://arxiv.org/pdf/1810.04805",
        "source": "semantic_scholar",
    }


@pytest.fixture
def mock_s2_response():
    """Mock Semantic Scholar search response."""
    return {
        "data": [
            {
                "title": "Gradient Coil Design Optimization",
                "authors": [{"name": "Alice Smith"}, {"name": "Bob Chen"}],
                "venue": "IEEE TMI",
                "year": 2023,
                "externalIds": {"DOI": "10.1109/tmi.2023.001"},
                "citationCount": 15,
                "abstract": "A novel gradient coil design method.",
                "openAccessPdf": {"url": "https://example.com/paper.pdf"},
            }
        ]
    }


@pytest.fixture
def mock_crossref_response():
    """Mock Crossref search response."""
    return {
        "message": {
            "items": [
                {
                    "title": ["Gradient Coil Design Optimization"],
                    "author": [{"given": "Alice", "family": "Smith"}],
                    "container-title": ["IEEE TMI"],
                    "published": {"date-parts": [[2023]]},
                    "DOI": "10.1109/tmi.2023.001",
                    "is-referenced-by-count": 15,
                    "abstract": "A novel gradient coil design method.",
                }
            ]
        }
    }


@pytest.fixture
def mock_unpaywall_response():
    """Mock Unpaywall API response."""
    return {
        "best_oa_location": {
            "url_for_pdf": "https://example.com/paper_oa.pdf"
        },
        "is_oa": True,
    }
