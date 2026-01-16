# JWT API Authentication

## Overview

JWT (JSON Web Token) is a standard for securing API endpoints and managing user authentication and authorization. JWTs are compact tokens that encode claims and are cryptographically signed to ensure integrity and authenticity.

## How JWT Authentication Works

1. **User Registration:** User provides credentials (username, email, password, role).
2. **User Login:** User logs in; backend generates and returns a JWT token.
3. **Token Usage:** Client stores the JWT and includes it in the `Authorization` header as a Bearer token for API requests.
4. **Backend Authorization:** Backend validates the JWT on each request, granting or denying access based on token validity.

## Example JWT Authentication Flow

1. **Register:**
	```http
	POST /api/register
	{
	  "username": "user1",
	  "password": "password123"
	}
	```

2. **Login:**
	```http
	POST /api/login
	{
	  "username": "user1",
	  "password": "password123"
	}
	// Response:
	{
	  "token": "<JWT_TOKEN>"
	}
	```

3. **Access Protected Endpoints:**
	- Use the JWT token in the `Authorization` header for subsequent API requests.

## Benefits of JWT Authentication

- Stateless and scalable (no server-side session storage)
- Secure (signed and optionally encrypted tokens)
- Flexible (supports custom claims)
- Interoperable across platforms and services
