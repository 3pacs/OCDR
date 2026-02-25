# OCDR Billing Reconciliation System

## Project Overview
Healthcare billing analytics and revenue cycle management application.
**Stack:** Python Flask + SQLite + Bootstrap 5 + Jinja2
**Constraint:** 100% LOCAL - zero cloud, zero internet, zero external APIs

## Running the App
```bash
pip install -r requirements.txt
python run.py
```
App runs at http://localhost:5000

## Project Structure
- `app/` - Flask application package
  - `__init__.py` - App factory with `create_app()`
  - `config.py` - Configuration
  - `models.py` - SQLAlchemy models
  - `ui/` - Blueprint routes (dashboard, chatbot)
- `templates/` - Jinja2 HTML templates
- `static/` - CSS, JS assets
- `instance/` - SQLite database (auto-created)
- `BUILD_SPEC.md` - Full technical specification

## Dev Notes / Chatbot System

The app includes a **Dev Notes** chatbot interface at `/chatbot`. This is a note-taking
system where the developer leaves actionable development tasks.

### How Claude Code Should Process Dev Notes

When reviewing this project, check for open dev notes by running the app and hitting:
```
GET http://localhost:5000/chatbot/api/notes/export
```

Or query the SQLite database directly:
```sql
SELECT id, content, category, priority, status, file_path
FROM dev_notes
WHERE status IN ('open', 'in_progress')
ORDER BY
  CASE priority
    WHEN 'critical' THEN 0
    WHEN 'high' THEN 1
    WHEN 'normal' THEN 2
    WHEN 'low' THEN 3
  END,
  created_at ASC;
```

**For each open note:**
1. Read the note content and understand the requested change
2. Implement the fix or feature described
3. Update the note status to `resolved` and add a `resolution` description via:
   ```
   PATCH /chatbot/api/notes/<id>
   {"status": "resolved", "resolution": "Description of what was done"}
   ```
   Or update the database directly:
   ```sql
   UPDATE dev_notes SET status = 'resolved', resolution = '...' WHERE id = <id>;
   ```

### Note Categories
- `bug` - Bug fixes needed
- `feature` - New feature requests
- `refactor` - Code improvement tasks
- `calendar` - Calendar feature tasks
- `general` - Miscellaneous dev notes

### Note Priorities
- `critical` - Fix immediately
- `high` - Fix soon
- `normal` - Standard priority
- `low` - Nice to have
