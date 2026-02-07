# open-workshop-accounts

## Tools

### Register user (password auth)
Create a new account with a password hash directly in the database.

```bash
python scripts/register_user.py <username>
python scripts/register_user.py <username> --password "secret123"
python scripts/register_user.py <username> --admin
```

The script uses DB settings from `ow_config.py`.
