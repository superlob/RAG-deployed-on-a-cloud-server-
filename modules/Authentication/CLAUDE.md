# CLAUDE.md

## Module: Authentication

Implement user registration and password-based login.

### Features

* User registration with username and password.
* User login with username and password.
* After registration, create the user's corresponding records/data in the shared PostgreSQL database.
* After successful login, establish the authenticated user session and navigate away from the authentication pages.

### Requirements

* Frontend handles the registration and login UI and API requests.
* Backend handles authentication, password management, and PostgreSQL operations.
* All user data must be isolated by user identity and follow the project's Row-Level Security rules.
* Do not hardcode API keys, host IPs, passwords, or other sensitive information.
* Test the registration and login flow after implementation.
