# Demo Pydantic Migration Repository 🦥

A standalone test repository designed specifically for testing **SlothMigrate** migrations from **Pydantic v1 to Pydantic v2**.

## 📌 Characteristics
- **No Database Dependency**: Completely self-contained in-memory models and services (no SQLite, SQLAlchemy, or Postgres).
- **Root Folder Layout**: All domain models, services, tests, and dependency manifests reside directly in the root folder.
- **Pydantic v1 Idioms Included**:
  - `class Config`: `anystr_strip_whitespace`, `validate_assignment`, `allow_population_by_field_name`
  - `@validator`: Field-level validation on `username` and `email`
  - `@root_validator`: Model-level multi-field calculation for order totals
  - `.parse_obj(...)`: Instantiation from dicts
  - `.dict()` & `.json()`: Serialization methods

## 🧪 Testing with SlothMigrate

### Direct CLI Run:
```bash
sloth-migrate run --path demo_pydantic_repo --package pydantic --version 2.14.1
```

### Durable Temporal Workflow:
Make sure the Temporal worker is running:
```bash
python -m sloth_migrate.workflows.worker
```
Then initiate the durable workflow:
```bash
sloth-migrate run --path demo_pydantic_repo --package pydantic --version 2.14.1 --durable
```

## 🔄 Resetting for Another Run
To revert changes back to Pydantic v1 after testing:
```bash
git checkout -- demo_pydantic_repo
```
