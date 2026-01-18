from setuptools import setup, find_packages

setup(
    name="mozilla_bug_analyzer",
    version="0.1.0",
    description="Tool for analyzing Mozilla bugs with LLMs",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.8",
    install_requires=[
        "requests",
        "google-generativeai",
        "python-dotenv",
    ],
    entry_points={
        'console_scripts': [
            'analyze-bug=mozilla_bug_analyzer.cli:main',
        ],
    },
)
