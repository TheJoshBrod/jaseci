# Jac Serve Command

The `jac serve` command turns your Jac programs into authenticated REST APIs automatically.

## Overview

When you run `jac serve`, it:
1. Executes your target Jac module
2. Converts all functions into REST API endpoints with introspected signatures
3. Converts all walkers into REST APIs where:
   - Walker fields (has variables) become the API interface
   - An additional `target_node` field specifies where to spawn the walker
4. Creates a user management system where each user has their own persistent root node
5. Requires authentication via token-based auth for all protected endpoints

## Usage

```bash
# Basic usage
jac serve myprogram.jac

# Specify a custom port
jac serve myprogram.jac --port 8080

# Use a specific session file for persistence
jac serve myprogram.jac --session myapp.session
```

## API Endpoints

### Public Endpoints (No Authentication Required)

#### GET /
Returns API information and available endpoints.

**Example:**
```bash
curl http://localhost:8000/
```

#### POST /user/create
Create a new user account. Each user gets their own persistent root node.

**Request Body:**
```json
{
  "username": "alice",
  "password": "secret123"
}
```

**Response:**
```json
{
  "username": "alice",
  "token": "abc123...",
  "root_id": "uuid-of-root-node"
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/user/create \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "secret123"}'
```

#### POST /user/login
Authenticate and receive a token.

**Request Body:**
```json
{
  "username": "alice",
  "password": "secret123"
}
```

**Response:**
```json
{
  "username": "alice",
  "token": "abc123...",
  "root_id": "uuid-of-root-node"
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/user/login \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "secret123"}'
```

### Protected Endpoints (Authentication Required)

All protected endpoints require an `Authorization` header with a Bearer token:

```
Authorization: Bearer YOUR_TOKEN_HERE
```

#### GET /functions
List all available functions in the module.

**Example:**
```bash
curl http://localhost:8000/functions \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Response:**
```json
{
  "functions": ["add_numbers", "greet", "calculate_stats"]
}
```

#### GET /function/<name>
Get the signature and parameter information for a specific function.

**Example:**
```bash
curl http://localhost:8000/function/add_numbers \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Response:**
```json
{
  "name": "add_numbers",
  "signature": {
    "parameters": {
      "a": {
        "type": "int",
        "required": true,
        "default": null
      },
      "b": {
        "type": "int",
        "required": true,
        "default": null
      }
    },
    "return_type": "int"
  }
}
```

#### POST /function/<name>
Call a function with the provided arguments.

**Request Body:**
```json
{
  "args": {
    "a": 5,
    "b": 10
  }
}
```

**Response:**
```json
{
  "result": 15,
  "reports": []
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/function/add_numbers \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"args": {"a": 5, "b": 10}}'
```

#### GET /walkers
List all available walkers in the module.

**Example:**
```bash
curl http://localhost:8000/walkers \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Response:**
```json
{
  "walkers": ["CreateTask", "ListTasks", "CompleteTask"]
}
```

#### GET /walker/<name>
Get the field information for a specific walker.

**Example:**
```bash
curl http://localhost:8000/walker/CreateTask \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Response:**
```json
{
  "name": "CreateTask",
  "info": {
    "fields": {
      "title": {
        "type": "str",
        "required": true,
        "default": null
      },
      "priority": {
        "type": "int",
        "required": false,
        "default": "1"
      },
      "target_node": {
        "type": "str (node ID, optional)",
        "required": false,
        "default": "root"
      }
    }
  }
}
```

#### POST /walker/<name>
Spawn a walker with the provided fields.

**Request Body:**
```json
{
  "fields": {
    "title": "Buy groceries",
    "priority": 2,
    "target_node": "optional-node-id"
  }
}
```

**Response:**
```json
{
  "result": "Walker executed successfully",
  "reports": []
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/walker/CreateTask \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"fields": {"title": "Buy groceries", "priority": 2}}'
```

## Complete Workflow Example

Here's a complete example using the `example_api.jac` file:

### 1. Start the server
```bash
jac serve example_api.jac
```

### 2. Create a user
```bash
TOKEN=$(curl -s -X POST http://localhost:8000/user/create \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "secret123"}' \
  | jq -r '.token')

echo "Token: $TOKEN"
```

### 3. Call a function
```bash
curl -X POST http://localhost:8000/function/add_numbers \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"args": {"a": 15, "b": 27}}'
```

### 4. Create tasks using walkers
```bash
# Create first task
curl -X POST http://localhost:8000/walker/CreateTask \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"fields": {"title": "Buy groceries", "priority": 2}}'

# Create second task
curl -X POST http://localhost:8000/walker/CreateTask \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"fields": {"title": "Write documentation", "priority": 1}}'
```

### 5. List all tasks
```bash
curl -X POST http://localhost:8000/walker/ListTasks \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"fields": {}}'
```

### 6. Complete a task
```bash
curl -X POST http://localhost:8000/walker/CompleteTask \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"fields": {"title": "Buy groceries"}}'
```

## Persistence

- Each user has their own **persistent root node** stored in the session file
- All nodes created by a user are attached to their root and persist across API calls
- The session file stores the graph structure and can be reused across server restarts
- Different users have isolated graph spaces - they cannot access each other's nodes

## Authentication

- Token-based authentication using Bearer tokens
- Tokens are generated during user creation and login
- All protected endpoints (functions and walkers) require a valid token
- Each request executes in the context of the authenticated user's root node

## Key Features

1. **Automatic API Generation**: Functions and walkers automatically become REST endpoints
2. **Type Introspection**: Function signatures are analyzed to generate API documentation
3. **User Isolation**: Each user has their own persistent root and graph space
4. **Session Persistence**: User data persists across server restarts via session files
5. **Standard Library Only**: Uses only Python standard libraries (http.server, json, hashlib, etc.)
6. **CORS Support**: Includes CORS headers for web application integration

## Notes

- The `target_node` field for walkers is optional and defaults to the user's root node
- If `target_node` is specified, it should be a valid node ID (hex string)
- All walker execution happens in the context of the authenticated user
- The server binds to `0.0.0.0` by default, making it accessible on all network interfaces
