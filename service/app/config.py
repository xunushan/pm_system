"""应用配置：从 .env / 环境变量读取。字段对应 docker-compose.yml 的 environment。"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 服务端口（uvicorn 监听端口；/api/v1 与 /webhook 同在此端口，单进程）
    api_port: int = 8001

    # 数据库（SQLite，唯一真相源）
    database_url: str = "sqlite:///./data/pm.db"

    # Redis（超时监控 / 缓存 / Supervisor 巡检去重）
    redis_url: str = "redis://localhost:6379/0"

    # OpenCode 智能体执行环境
    opencode_base_url: str = "http://localhost:8080"
    agent_port_range: str = "10000-20000"

    # 飞书开放平台
    feishu_app_id: str = ""
    feishu_app_secret: str = ""

    # H5 页面基址（pm 配置类指令生成预填链接用）
    h5_base_url: str = "http://localhost:5173"

    # Supervisor 巡检开关
    supervisor_enabled: bool = True

    def ensure_data_dir(self) -> None:
        """确保 SQLite 数据文件所在目录存在。"""
        if not self.database_url.startswith("sqlite"):
            return
        path_part = self.database_url.split("///")[-1]  # sqlite:///./data/pm.db -> ./data/pm.db
        db_path = Path(path_part)
        if not db_path.is_absolute():
            db_path = Path.cwd() / db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_data_dir()
