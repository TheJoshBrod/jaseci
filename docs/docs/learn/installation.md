# Getting Started with Jac: Installation, Setup, and Your First Program
---
The first step is setting up your development environment. We'll cover how to install Jac, configure your code editor, and write and run your first program.


> To get started, you will need Python 3.12 or newer. While you can use any text editor, we recommend using VS Code with the official Jac extension for the best experience, as it provides helpful features like syntax highlighting and error checking.

## Installation and IDE Setup
---
### System Requirements
- Python 3.12 or higher
- pip package manager
- 4GB RAM minimum (8GB recommended)
- 500MB storage for Jac and dependencies


### Installing Jac
We recommend installing Jac in a virtual environment to keep your project's dependencies separate from your system's Python packages.

#### Quick Install via pip

```bash
# Install Jac from PyPI
$ pip install jaclang

# Verify installation
$ jac --version
```
<br />

#### Via Virtual Environment (Recommended)

For project isolation, consider using a virtual environment:

**Linux/MacOS**

```bash
# Create virtual environment
$ python -m venv jac-env

# Activate it (Linux/Mac)
$ source jac-env/bin/activate

# Install Jac
$ pip install jaclang
```
<br />

**Windows**
```powershell
# Create virtual environment
python -m venv jac-env

# Activate it (Windows)
jac-env\Scripts\activate

# Install Jac
pip install jaclang
```
<br />

### VS Code Extension
For the best development experience, install the Jac VS Code extension:

**For VS Code users:**


1. Open VS Code
2. Go to Extensions (Ctrl+Shift+X)
3. Search for "Jac"
4. Install the official Jac extension

**For Cursor users:**

1. Go to the [latest Jaseci release page](https://github.com/Jaseci-Labs/jaseci/releases/latest)
2. Download the latest `jaclang-extension-*.vsix` file from the release assets
3. Open Cursor
4. Press `Ctrl+Shift+P` (or `Cmd+Shift+P` on Mac)
5. Type `>install from vsix` and select the command
6. Select the downloaded VSIX file
7. The extension will be installed and ready to use

Alternatively, visit the [VS Code marketplace](https://marketplace.visualstudio.com/items?itemName=jaseci-labs.jaclang-extension) directly.

The extension provides:

- Color-coding for Jac's syntax to make it easier to read.
- Automatic detection of errors in your code.
- Tools for formatting your code consistently.
- Visualizations of your graph data structures.

### Basic CLI Commands
Jac provides a simple command-line interface (CLI) for running scripts and managing projects. This cli provides developers the ability to either run scripts locally for testing or [even serve them as web applications](../chapter_12). Here are the most common commands:
```bash
# Run a Jac file
$ jac run filename.jac

# Get help
$ jac --help

# Serve as web application (advanced)
$ jac serve filename.jac
```
<br />

## Hello World in Jac
---
Let's write and run your first Jac program.
1. Create a new file named hello.jac.
2. Add the following code to the file:

```jac
# hello.jac
with entry {
    print("Hello, Jac World!");
}
```
<br />

Run the program from your terminal.
```bash
$ jac run hello.jac
```
<br />

You will see the following output:

<br />

```bash
Hello, Jac World!
```
<br />

If you see this information, you have installed Jac successfully! You're ready to write your first program.



## Next Steps

<div class="grid cards" markdown>

-   __Jac in a Flash__

    ---

    *See Jac's Syntax with a Toy*

    [Jac in a Flash](jac_in_a_flash.md){ .md-button .md-button--primary }

-   __A Real World Example__

    ---

    *See somthing real in Jac*

    <!-- [:octicons-arrow-right-24: Getting started](#) -->

    [A Robust Example](examples/littleX/tutorial.md){ .md-button }

-   __Experience Jac in Browser__

    ---

    *Hit the Playground*

    [Jac Playground](../playground/index.html){ .md-button .md-button--primary }

</div>
