# Campus Lost & Found

A Flask and SQLite web application for a DBMS project. Students can browse available items, while Coordinators handle item entry, updates, claims, and handovers. Super Admins oversee all records and manage Coordinator accounts.

## Run Locally

1. Create a virtual environment:

   ```powershell
   py -m venv .venv
   ```

2. Activate the virtual environment:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

3. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

4. Start the application:

   ```powershell
   python app.py
   ```

Open the student portal at http://127.0.0.1:5000.

### Portals

* **Student Portal:** `/`
* **Coordinator Portal:** `/coordinator/login`
* **Super Admin Portal:** `/admin/login`

### Default Demo Credentials

| Role        | Account ID    | Password         |
| ----------- | ------------- | ---------------- |
| Super Admin | `admin`       | `admin123`       |
| Coordinator | `coordinator` | `coordinator123` |

**Security note:** Change the default credentials and `SECRET_KEY` before deploying the application publicly.

## Database Design

* **`admins`:** Stores Super Admin and Coordinator accounts, roles, active status, and securely hashed passwords.
* **`items`:** Stores item names, descriptions, buildings (`TT`, `SJT`, or `PRP`), submission timestamps, images, statuses, and creators.
* **`collections`:** Records returned items, including the student's register number, collection time, and processing administrator.
* **`claimed_objects`:** Stores claims recorded by Coordinators at the desk, including the student's name, register number, email, and claim time.

## Access Control

### Super Admin

* View the complete item, claim, and collection audit records.
* Edit or permanently delete items and their linked records.
* Create, update, activate, deactivate, and delete unused Coordinator accounts.

### Coordinator

* Add and edit items.
* Record claims on behalf of students visiting the desk.
* Review student claims.
* Record physical handovers.
* Cannot access account management or the full audit portal.

## Storage

The SQLite database (`lost_and_found.db`) and uploaded images are created automatically on the first run.
