from setuptools import setup, find_packages

setup(
    name="excellence-agent",
    version="0.1.0",
    description="ExcellenceAgent — APRL v2 report analyser and ADO work-item generator",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=[
        "openpyxl>=3.1.0",
        "pandas>=2.0.0",
        "click>=8.1.0",
        "flask>=3.0.0",
        "Jinja2>=3.1.0",
        "python-dotenv>=1.0.0",
        "openai>=1.0.0",
        "PyYAML>=6.0.0",
    ],
    entry_points={
        "console_scripts": [
            "excellence-agent=excellence_agent.cli:cli",
        ],
    },
)
