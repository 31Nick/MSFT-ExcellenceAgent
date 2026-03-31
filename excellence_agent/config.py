import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()


@dataclass
class ADOConfig:
    """Azure DevOps export configuration."""
    work_item_type_epic: str = "Epic"
    work_item_type_feature: str = "Feature"
    work_item_type_story: str = "User Story"
    work_item_type_task: str = "Task"
    area_path: str = ""
    iteration_path: str = ""


@dataclass
class AzureOpenAIConfig:
    """Azure OpenAI enrichment configuration."""
    endpoint: str = ""
    api_key: str = ""
    deployment: str = ""
    api_version: str = "2024-02-01"

    @property
    def is_configured(self) -> bool:
        return bool(self.endpoint and self.api_key and self.deployment)


@dataclass
class Config:
    """Root configuration for ExcellenceAgent."""
    aprl_report_path: str = ""
    resource_matrix_path: str = ""
    ado: ADOConfig = field(default_factory=ADOConfig)
    openai: AzureOpenAIConfig = field(default_factory=AzureOpenAIConfig)
    flask_port: int = 5000
    output_dir: str = "./output"

    @classmethod
    def from_env(cls, matrix_path: str | None = None) -> "Config":
        """Load configuration from environment variables."""
        project_root = Path(__file__).parent.parent

        return cls(
            aprl_report_path=os.getenv("APRL_REPORT_PATH", ""),
            resource_matrix_path=matrix_path or str(project_root / "resource_matrix.yaml"),
            ado=ADOConfig(
                work_item_type_epic=os.getenv("ADO_WORK_ITEM_TYPE_EPIC", "Epic"),
                work_item_type_feature=os.getenv("ADO_WORK_ITEM_TYPE_FEATURE", "Feature"),
                work_item_type_story=os.getenv("ADO_WORK_ITEM_TYPE_STORY", "User Story"),
                work_item_type_task=os.getenv("ADO_WORK_ITEM_TYPE_TASK", "Task"),
                area_path=os.getenv("ADO_AREA_PATH", ""),
                iteration_path=os.getenv("ADO_ITERATION_PATH", ""),
            ),
            openai=AzureOpenAIConfig(
                endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
                api_key=os.getenv("AZURE_OPENAI_API_KEY", ""),
                deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", ""),
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
            ),
            flask_port=int(os.getenv("FLASK_PORT", "5000")),
        )

    def load_resource_matrix(self) -> dict:
        """Load the resource matrix YAML file."""
        path = Path(self.resource_matrix_path)
        if not path.exists():
            raise FileNotFoundError(f"Resource matrix not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
