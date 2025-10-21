# JSX-Based Webpage Generation Design Document

## Overview

This document describes how Jac's `cl` (client) keyword produces browser-ready web experiences. Client-marked declarations compile to JavaScript and ship through `jac serve` as static bundles that execute entirely in the browser. The current implementation is **CSR-only** (Client-Side Rendering): the server returns an empty HTML shell with bootstrapping metadata and a JavaScript bundle that handles all rendering in the browser.

## Architecture Overview

```mermaid
graph TD
    subgraph "Development - Compilation"
        A[Jac source with cl] --> B[Jac Compiler]
        B --> C[PyAST Gen Pass<br/>pyast_gen_pass.py]
        B --> D[ESTree Gen Pass<br/>esast_gen_pass.py]
        C --> E[Python module<br/>.py output]
        D --> F[JavaScript code<br/>module.gen.js]
    end

    subgraph "Runtime - Serving"
        E --> H[JacAPIServer]
        F --> I[ClientBundleBuilder]
        H --> J[GET /page/fn]
        I --> K["/static/client.js"]
        J --> L[HTML shell + init payload]
        K --> M[Runtime + Module JS]
        L --> N[Browser]
        M --> N
        N --> O[Hydrate & Execute]
        O --> P[Render JSX to DOM]
    end
```

### CSR Execution Flow

1. **Compilation**: When a `.jac` file is compiled:
   - The `cl` keyword marks declarations for client-side execution
   - `pyast_gen_pass.py` skips Python codegen for client-only nodes (via `_should_skip_client`)
   - `esast_gen_pass.py` generates ECMAScript AST and JavaScript code
   - Client metadata is collected in `ClientManifest` (exports, globals, params)

2. **Bundle Generation**: `ClientBundleBuilder` creates the browser bundle:
   - Compiles [client_runtime.jac](../jaclang/runtimelib/client_runtime.jac) to provide JSX and walker runtime
   - Compiles the application module's client-marked code
   - Generates registration code that exposes functions globally
   - Includes polyfills (e.g., `Object.prototype.get()` for dict-like access)

3. **Page Request**: When `GET /page/<function_name>` is requested:
   - Server returns minimal HTML with empty `<div id="__jac_root"></div>`
   - Embeds `<script id="__jac_init__">` with JSON payload containing:
     - Module name and function name to execute
     - Arguments and their ordering
     - Global variable values
   - Links to `<script src="/static/client.js?hash=...">` bundle

4. **Client Execution**: On DOM load, the browser:
   - Parses the `__jac_init__` payload
   - Looks up the requested function from the global registry
   - Restores client global variables
   - Executes the function with provided arguments
   - Calls `renderJsxTree()` to render the returned JSX into `__jac_root`

> **Note**: SSR + hydration is not currently implemented. All rendering happens on the client.

## Language Features

### 1. The `cl` (Client) Keyword

The `cl` keyword marks Jac declarations for **client-side compilation**. This enables a single `.jac` file to contain both:
- **Server-side code** (compiled to Python via `pyast_gen_pass`)
- **Client-side code** (compiled to JavaScript via `esast_gen_pass`)

When `cl` is present:
- Node is marked with `is_client_decl = True`
- Python codegen is skipped for the declaration (via `_should_skip_client()` in [pyast_gen_pass.py:310-312](../jaclang/compiler/passes/main/pyast_gen_pass.py#L310-L312))
- JavaScript codegen generates ECMAScript AST (in [esast_gen_pass.py](../jaclang/compiler/passes/ecmascript/esast_gen_pass.py))
- The declaration is tracked in the module's `ClientManifest` (exports, globals, params, globals_values, imports)

#### Supported Constructs

```jac
// Client function - executes in browser, can return JSX
cl def homepage() -> dict {
    return <div>
        <h1>Welcome</h1>
        <button onclick={load_feed()}>Load Feed</button>
    </div>;
}

// Client object - available on both client and server
cl obj ButtonProps {
    has label: str = "Hello";
    has count: int = 0;
}

// Client global - literal value sent to browser
cl let API_BASE_URL: str = "https://api.example.com";
```

#### Grammar Definition

From [jac.lark:9-10, 591](../jaclang/compiler/jac.lark#L9-L10):

```lark
toplevel_stmt: KW_CLIENT? onelang_stmt
       | KW_CLIENT LBRACE onelang_stmt* RBRACE
       | py_code_block

KW_CLIENT: "cl"
```

The `cl` keyword can prefix individual statements or wrap multiple statements in braces.

### 2. Client Imports

Client code can import functions and utilities from the built-in `jac:client_runtime` module using the `cl import` syntax. This allows client-side code to access the runtime's JSX rendering, authentication helpers, and server interaction functions.

#### Syntax

```jac
cl import from jac:client_runtime {
    renderJsxTree,
    jacLogin,
    jacLogout,
    jacSignup,
    jacIsLoggedIn,
}
```

#### Available Exports from `jac:client_runtime`

The client runtime ([client_runtime.jac](../jaclang/runtimelib/client_runtime.jac)) exports these public functions for use in client code:

| Function | Signature | Description |
|----------|-----------|-------------|
| `renderJsxTree` | `(node: any, container: any) -> None` | Renders a JSX tree into a DOM container |
| `jacSignup` | `async (username: str, password: str) -> dict` | Creates a new user account and returns `{success, token, username}` or `{success, error}` |
| `jacLogin` | `async (username: str, password: str) -> bool` | Authenticates user and stores token in localStorage |
| `jacLogout` | `() -> None` | Clears authentication token from localStorage |
| `jacIsLoggedIn` | `() -> bool` | Checks if user has valid token in localStorage |

> **Note**: Functions prefixed with `__jac` (like `__jacJsx`, `__buildDom`, `__jacSpawn`, etc.) are internal runtime functions automatically available in the client bundle. They should not be imported directly - use the public API functions listed above instead.

#### How Client Imports Work

When processing client imports ([esast_gen_pass.py:317-325](../jaclang/compiler/passes/ecmascript/esast_gen_pass.py#L317-L325)):

1. **Parser detects** `cl import from jac:client_runtime` syntax
   - The `jac:` prefix indicates a special runtime import
   - The import is marked with `is_client_decl = True`

2. **ESTree generation** creates JavaScript import declaration:
   ```javascript
   import { renderJsxTree, jacLogin } from "jac:client_runtime";
   ```

3. **Manifest tracking** records the import in `ClientManifest.imports`:
   - Key: `"client_runtime"` (from `dot_path_str`)
   - Value: Resolved path to `client_runtime.jac`

4. **Bundle generation** compiles `client_runtime.jac` into the bundle, making these functions available globally

#### Example Usage

```jac
cl import from jac:client_runtime {
    jacLogin,
    jacLogout,
    jacIsLoggedIn,
}

cl def LoginForm() {
    async def handleLogin(event: any) {
        event.preventDefault();
        let username = document.getElementById("username").value;
        let password = document.getElementById("password").value;

        success = await jacLogin(username, password);
        if success {
            console.log("Login successful!");
            // Redirect or update UI
        } else {
            console.log("Login failed");
        }
    }

    return <form onsubmit={handleLogin}>
        <input id="username" type="text" placeholder="Username" />
        <input id="password" type="password" placeholder="Password" />
        <button type="submit">Login</button>
    </form>;
}
```

### 3. JSX Syntax

JSX is fully supported in Jac with grammar defined in [jac.lark:448-473](../jaclang/compiler/jac.lark#L448-L473). JSX elements are transpiled to `__jacJsx(tag, props, children)` calls by [jsx_processor.py:30-129](../jaclang/compiler/passes/ast_gen/jsx_processor.py#L30-L129) via the `EsJsxProcessor` class.

#### JSX Features

```jac
cl def render_example() {
    // Basic elements
    let basic = <div>Hello World</div>;

    // Elements with attributes
    let with_attrs = <button id="submit" class="btn">Click</button>;

    // Expression attributes and children
    let name = "Alice";
    let greeting = <h1 data-user={name}>Welcome, {name}!</h1>;

    // Spread attributes
    let props = {"class": "card", "id": "main"};
    let with_spread = <div {...props}>Content</div>;

    // Fragment syntax
    let fragment = <>
        <div>First</div>
        <div>Second</div>
    </>;

    // Component usage (capitalized names)
    let component = <Button label="Click Me" />;

    return <div>{greeting}{component}</div>;
}
```

#### JSX Transpilation

JSX elements compile to function calls:
- `<div>Hello</div>` → `__jacJsx("div", {}, ["Hello"])`
- `<Button {...props} />` → `__jacJsx(Button, Object.assign({}, props), [])`
- Tag names starting with lowercase become string literals
- Tag names starting with uppercase become identifier references
- Props merge via `Object.assign()` when spreads are present

## Implementation Details

### Core Components

| Component | Implementation | Key Responsibilities |
|-----------|----------------|---------------------|
| **Compiler Passes** | | |
| [pyast_gen_pass.py](../jaclang/compiler/passes/main/pyast_gen_pass.py) | Python AST generation | Skips Python codegen for `cl`-marked nodes |
| [esast_gen_pass.py](../jaclang/compiler/passes/ecmascript/esast_gen_pass.py) | ECMAScript AST generation | Generates JavaScript for `cl`-marked nodes, JSX transpilation |
| [es_unparse.py](../jaclang/compiler/passes/ecmascript/es_unparse.py) | JavaScript code generation | Converts ESTree AST to JavaScript source |
| **Runtime Components** | | |
| [client_bundle.py](../jaclang/runtimelib/client_bundle.py) | Bundle builder | Compiles runtime + module, generates registration code |
| [client_runtime.jac](../jaclang/runtimelib/client_runtime.jac) | Client runtime | JSX rendering (`__jacJsx`, `renderJsxTree`), walker spawning (`__jacSpawn`), auth helpers |
| [server.py](../jaclang/runtimelib/server.py) | HTTP server | Serves pages (`/page/<fn>`), bundles (`/static/client.js`), walkers |
| **Data Structures** | | |
| [ClientManifest](../jaclang/compiler/codeinfo.py#L15-L25) | Metadata container (in codeinfo.py) | Stores `exports` (function names), `globals` (var names), `params` (arg order), `globals_values` (literal values), `has_client` (bool), `imports` (module mappings) |

### Client Bundle Structure

The bundle generated by `ClientBundleBuilder` contains (in order):

1. **Polyfills** - Browser compatibility shims (from [client_runtime.jac:227-253](../jaclang/runtimelib/client_runtime.jac#L227-L253)):
   The `__jacEnsureObjectGetPolyfill()` function adds a Python-style `.get()` method to `Object.prototype`:
   ```javascript
   Object.prototype.get = function(key, defaultValue) {
       if (this.hasOwnProperty(key)) {
           return this[key];
       }
       return defaultValue !== undefined ? defaultValue : null;
   };
   ```
   This polyfill is called automatically during module registration and hydration.

2. **Client Runtime** - Compiled from [client_runtime.jac](../jaclang/runtimelib/client_runtime.jac):
   - `__jacJsx(tag, props, children)` - JSX factory function
   - `renderJsxTree(node, container)` - DOM rendering
   - `__buildDom(node)` - Recursive DOM builder
   - `__applyProp(element, key, value)` - Attribute/event handler application
   - `__jacSpawn(walker, fields)` - Async walker invocation via `/walker/<name>` endpoint
   - `__jacCallFunction(function_name, args)` - Async server-side function calls via `/function/<name>` endpoint
   - Auth helpers: `jacSignup`, `jacLogin`, `jacLogout`, `jacIsLoggedIn`
   - Registration and hydration: `__jacRegisterClientModule`, `__jacHydrateFromDom`, `__jacEnsureHydration`

3. **Application Module** - Transpiled user code with `cl` declarations

4. **Registration Code** - Generated by [client_bundle.py:245-251](../jaclang/runtimelib/client_bundle.py#L245-L251):
   ```javascript
   __jacRegisterClientModule("module_name", ["homepage", "other_func"], {"API_URL": "value"});
   ```

   This calls the `__jacRegisterClientModule` function from the runtime which:
   - Registers all exported client functions in the global registry
   - Sets up client global variables with default values
   - Creates a module record in `__jacClient.modules`
   - Calls `__jacEnsureHydration` to set up DOMContentLoaded listener
   - Executes hydration automatically when DOM is ready

### Server Endpoints

From [server.py](../jaclang/runtimelib/server.py):

| Endpoint | Method | Description | Implementation |
|----------|--------|-------------|----------------|
| `/page/<fn>` | GET | Render HTML page for client function | Lines 806-830 |
| `/static/client.js` | GET | Serve compiled JavaScript bundle | Lines 772-781 |
| `/walker/<name>` | POST | Spawn walker on node | Handled by ExecutionHandler |
| `/function/<name>` | POST | Call server-side function | Handled by ExecutionHandler |
| `/user/create` | POST | Create new user account | Handled by AuthHandler |
| `/user/login` | POST | Authenticate and get token | Handled by AuthHandler |
| `/functions` | GET | List available functions | Handled by IntrospectionHandler |
| `/walkers` | GET | List available walkers | Handled by IntrospectionHandler |

> **Note**: The server has been refactored to use handler classes (AuthHandler, IntrospectionHandler, ExecutionHandler) for better organization.

#### Page Rendering Flow

When `GET /page/homepage?arg1=value1` is requested:

1. **Parse request** - Extract function name and query params
2. **Authenticate** - Check auth token, or create guest user
3. **Load module** - Ensure module is loaded and manifest is available
4. **Validate function** - Check function is in `client_exports`
5. **Build payload** - Serialize args, globals, arg order
6. **Render HTML** - Return shell with embedded payload and script tag

HTML template (from [server.py:491-504](../jaclang/runtimelib/server.py#L491-L504)):
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8"/>
    <title>homepage</title>
</head>
<body>
    <div id="__jac_root"></div>
    <script id="__jac_init__" type="application/json">{"module":"myapp","function":"homepage","args":{},"globals":{},"argOrder":[]}</script>
    <script src="/static/client.js?hash=abc123..." defer></script>
</body>
</html>
```

### Client-Side Execution

On page load in the browser:

1. **Wait for DOM** - Registration code waits for `DOMContentLoaded`
2. **Parse payload** - Extract `__jac_init__` JSON
3. **Restore globals** - Set global variables from payload
4. **Lookup function** - Find target function in `__jacClient.functions`
5. **Order arguments** - Map args dict to positional array using `argOrder`
6. **Execute function** - Call function with arguments
7. **Handle result** - If Promise, await; otherwise render immediately
8. **Render JSX** - Call `renderJsxTree(result, __jac_root)`

From [client_runtime.jac:470-488](../jaclang/runtimelib/client_runtime.jac#L470-L488):
```jac
callOutcome = __jacSafeCallTarget(target, scope, orderedArgs, targetName);
if not callOutcome or not callOutcome.get("ok") {
    return;
}
value = callOutcome.get("value");

if value and __isObject(value) and __isFunction(value.then) {
    value.then(
        lambda node: any -> None {
            __jacApplyRender(renderer, rootEl, node);
        }
    ).catch(
        lambda err: any -> None {
            console.error("[Jac] Error resolving client function promise", err);
        }
    );
} else {
    __jacApplyRender(renderer, rootEl, value);
}
```

### JSX Rendering

The `renderJsxTree` function ([client_runtime.jac:9-11](../jaclang/runtimelib/client_runtime.jac#L9-L11)) calls `__buildDom` ([client_runtime.jac:14-50](../jaclang/runtimelib/client_runtime.jac#L14-L50)) to recursively build DOM:

1. **Null/undefined** → Empty text node
2. **Primitive values** → Text node with `String(value)`
3. **Object with callable `tag`** → Execute component function, recurse
4. **Object with string `tag`** → Create element:
   - Apply props (attributes, event listeners, styles)
   - Recursively build and append children
5. **Return DOM node** → Attach to container

Event handlers are bound in `__applyProp` ([client_runtime.jac:53-68](../jaclang/runtimelib/client_runtime.jac#L53-L68)):
- Props starting with `on` become `addEventListener(event, handler)`
- `onclick` → `click`, `onsubmit` → `submit`, etc.
- `class` and `className` set `element.className`
- `style` objects are applied to `element.style[key]`

## Example Usage

### Complete Application

```jac
// Server-side data model
node User {
    has name: str;
    has email: str;
}

// Client-side global configuration
cl let API_URL: str = "/api";

// Client-side component
cl obj CardProps {
    has title: str = "Untitled";
    has content: str = "";
}

// Client page - renders in browser
cl def homepage() {
    return <div class="app">
        <header>
            <h1>Welcome to Jac</h1>
        </header>
        <main>
            <p>Full-stack web development in one language!</p>
            <button onclick={load_users()}>Load Users</button>
        </main>
    </div>;
}

// Server-side walker - called from client via spawn
walker LoadUsers {
    has users: list = [];

    can process with `root entry {
        # Fetch users from database
        self.users = [{"name": "Alice"}, {"name": "Bob"}];
        report self.users;
    }
}
```

### Running the Application

```bash
# Compile the Jac file
jac myapp.jac

# Start the server
jac serve myapp.jac

# Access the page
# Browser: http://localhost:8000/page/homepage
```

### Client-Server Interaction

When the user clicks "Load Users":

1. **Client**: `spawn load_users()` triggers `__jacSpawn("LoadUsers", {})`
2. **HTTP**: Async `POST /walker/LoadUsers` with `{"nd": "root"}` and Authorization header
3. **Server**: Authenticates user, spawns `LoadUsers` walker on root node
4. **Server**: Walker executes, generates reports
5. **HTTP**: Returns `{"result": {...}, "reports": [...]}`
6. **Client**: Receives walker results as Promise (can be awaited to update UI)

The `__jacSpawn` function ([client_runtime.jac:71-92](../jaclang/runtimelib/client_runtime.jac#L71-L92)) is async and retrieves the auth token from localStorage before making the request.

## Test Coverage

| Test Suite | Location | Coverage |
|------------|----------|----------|
| **Client codegen tests** | [test_client_codegen.py](../jaclang/compiler/tests/test_client_codegen.py) | `cl` keyword detection, manifest generation |
| **ESTree generation tests** | [test_esast_gen_pass.py](../jaclang/compiler/passes/ecmascript/tests/test_esast_gen_pass.py) | JavaScript AST generation |
| **JavaScript generation tests** | [test_js_generation.py](../jaclang/compiler/passes/ecmascript/tests/test_js_generation.py) | JS code output from ESTree |
| **Client bundle tests** | [test_client_bundle.py](../jaclang/runtimelib/tests/test_client_bundle.py) | Bundle building, caching |
| **Server endpoint tests** | [test_serve.py](../jaclang/runtimelib/tests/test_serve.py) | HTTP endpoints, page rendering |
| **JSX rendering tests** | [test_jsx_render.py](../jaclang/runtimelib/tests/test_jsx_render.py) | JSX parsing and rendering |

### Example Test Fixtures

- [client_jsx.jac](../jaclang/compiler/passes/ecmascript/tests/fixtures/client_jsx.jac) - Comprehensive client syntax examples
- [jsx_elements.jac](../examples/reference/jsx_elements.jac) - JSX feature demonstrations

