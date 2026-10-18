"""Загрузка ORM-моделей модулей для регистрации в Base.metadata."""

from importlib import import_module
from pathlib import Path

import src.modules


def load_models() -> tuple[str, ...]:
    """Импортировать src/modules/*/infrastructure/db/models.py."""
    loaded: list[str] = []
    for package_root in src.modules.__path__:
        for module_dir in sorted(Path(package_root).iterdir()):
            if not module_dir.is_dir() or not (module_dir / "__init__.py").is_file():
                continue
            db_dir = module_dir / "infrastructure" / "db"
            if not db_dir.is_dir():
                continue
            if not (db_dir / "models.py").is_file():
                raise FileNotFoundError(f"Missing ORM model entrypoint: {db_dir / 'models.py'}")
            module_name = f"src.modules.{module_dir.name}.infrastructure.db.models"
            import_module(module_name)
            loaded.append(module_name)
    return tuple(loaded)
