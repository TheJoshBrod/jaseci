# Jac debugging in VS Code

---
The first step in debugging a Jac program is deciding if you are using the online debugger with the [Jac Playground](https://www.jac-lang.org/playground/) or the VS Code Extension to debug on your own machine. 

In this tutorial we will cover how to setup and fully utilize the VS Code debugger. 

If you want to learn more about the online debugger check out the [Jac Playground Tutorial](https://www.jac-lang.org/learn/jac_playground/). 

!!! important
    To get started, you will need Python 3.12 or later and jaclang 0.8.10 or later installed.

!!! info
    You can write and run Jac code in any text editor, but currently, debugging is only supported in Visual Studio Code using the official Jac extension.
    This extension offers features such as breakpoints, syntax highlighting, error checking, and graph visualization.

## Setup (one time)
---

!!! info
    This is the information to set up the tools to use the Jac debugger. These steps should be followed ONLY ONCE.

### Requirements
- Python 3.12 or later
- jaclang 0.8.10 or later 

### Jac Environment Setup

Before following this tutorial, make sure you have read the [Jac Installation Guide](https://www.jac-lang.org/learn/installation/) for details on setting up your first Jac environment.

### Visual Studio Code Setup

Make sure you have VS Code text editor installed on your device. 

If you do not have it installed go to [Visual Studio Code](https://code.visualstudio.com/) to install the program.

Once, installed follow the video below:

1. Open settings menu
2. Search for "breakpoints"
3. Select `Debug: Allow Breakpoints Everywhere`

<video width="640" height="360" controls>
  <source src=".assets/debugger/1030.mp4" type="video/mp4">
  Your browser does not support the video tag.
</video>

### Jac Debugger Setup

Once VS Code is installed, go to the extensions tab and search `jac` and install the following extension:

![Jac Extension Page](./assets/debugger/debugger-extension.png){: style="display: block; margin: auto;"}


## Setup (every time)

!!! info
    These steps should be followed EVERY time you create a new Jac project.

### Setting up launch.json

A `launch.json` file is a vscode configuration file that tells the debugger how to run the program (i.e. what args to pass in, what version of Jac to use, etc.)

First opening the `Run and Debug` menu on the VS Code tool bar, selecting we want to `create a launch.json file`.


![Create Launch Dot Json](./assets/debugger/debugger-create-launch_dot_json.png){: style="display: block; margin: auto;"}



This will open a menu prompting you to select which templated `launch.json` to create. We want to select `Jac Debug`.


![Create Jac's Launch Dot Json](./assets/debugger/debugger-create-jac-launch_dot_json.png){: style="display: block; margin: auto;"}



This will create the templated `launch.json` file and your screen should look something like this



![Verify Jac's Launch Dot Json Looks Correct](./assets/debugger/debugger-verify-launch_dot_json.png){: style="display: block; margin: auto;"}


If you see this screen you successfully set up your Jac Debugger!

## Debugger Tutorial

--

### How to use breakpoints

_TODO_

### How to use the graph visualizer

_TODO_

