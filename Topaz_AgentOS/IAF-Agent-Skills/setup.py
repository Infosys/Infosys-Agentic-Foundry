from setuptools import find_packages, setup


setup(
    name="iaf-agent-skills",
    version="1.0.0",
    description="Skill-based routing and generic agent framework built on IAF-Agent-OS",
    packages=find_packages(include=["iaf_agent_skills", "iaf_agent_skills.*"]),
    include_package_data=True,
    python_requires=">=3.10",
    install_requires=[
        "agentos-contracts>=0.1.0",
        "agentos-model>=0.1.0",
        "pyyaml>=6.0",
        "langchain>=0.3.0",
        "langchain-core>=0.3.0",
        "langchain-openai>=0.2.0",
        "langgraph>=0.2.0",
    ],
)