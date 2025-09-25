<h1 style="color: orange; font-weight: bold; text-align: center;">Getting Started With Jac and Jaseci</h1>

# Installation

Firstly make sure that Python 3.12 or higher is installed in your environment, then simply install Jac using pip:

```bash
python -m pip install -U jaclang
```

Once you've got Jaclang installed, just give the Jac CLI a try to make sure everything's up and running smoothly.

- Start the Jac CLI:
    ```bash
    jac --version
    ```
- Run a .jac file
    ```bash
    jac run <file_name>.jac
    ```
- To test run a 'Hello World' Program
    ```bash
    echo "with entry { print('Hello world'); }" > test.jac;
    jac run test.jac;
    rm test.jac;
    ```
> **Note**
>
> If these commands prints ```Hello world``` you are good to go.

## <span style="color: orange">Installing the VS Code Extension</span>

In addition to setting up JacLang itself, you may also want to take advantage of the JacLang language extension for Visual Studio Code (VSCode) or Cursor. This will give you enhanced code highlighting, autocomplete, and other useful language features within your editor environment.

**For VS Code users:**
- Visit the VS Code marketplace and install the [Jac Extension](https://marketplace.visualstudio.com/items?itemName=jaseci-labs.jaclang-extension)

**For Cursor users:**
1. Download the VSIX file: [jaclang-extension-2025.7.17.vsix](../../assets/vsce/jaclang-extension-2025.7.17.vsix)
2. Open Cursor
3. Press `Ctrl+Shift+P` (or `Cmd+Shift+P` on Mac)
4. Type `>install from vsix` and select the command
5. Select the downloaded `jaclang-extension-2025.7.17.vsix` file

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

