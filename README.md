# Campus Lost & Found

A Flask and SQLite web application for a DBMS project. Students can only browse available items. Coordinators handle day-to-day item entry, updates, desk claims, and handovers; Super Admins oversee the complete record and manage Coordinator accounts.

## Run locally

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000` for the student view.

- Coordinator portal: `http://127.0.0.1:5000/coordinator/login`
- Super Admin portal: `http://127.0.0.1:5000/admin/login`

Default demo credentials:

| Role | Account ID | Password |
| --- | --- |
| Super Admin | `admin` | `admin123` |
| Coordinator | `coordinator` | `coordinator123` |

Change these credentials and the `SECRET_KEY` before hosting publicly.

## Database design

- `admins`: both Super Admin and Coordinator identities, role, active state, and securely hashed passwords.
- `items`: item name, description, building (`TT`, `SJT`, or `PRP`), submission timestamp, image, status, and creator.
- `collections`: one collection record per returned item, including the student's register number, collection time, and processing admin.
- `claimed_objects`: one claim record per item, entered by a Coordinator after a student visits the desk, including the student's name, register number, email, and claim time.

## Access control

- **Super Admin:** access the full item/claim/collection audit record; edit or permanently delete any item and its linked records; and create, update, activate, deactivate, or delete unused Coordinator accounts.
- **Coordinator:** add and edit items, record a claim on behalf of a student at the desk, review student claims, and record physical handovers. This role cannot access account management or the full audit portal.

The SQLite database (`lost_and_found.db`) and uploaded images are created automatically on first run.
