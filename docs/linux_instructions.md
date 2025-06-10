# Linux/macOS Installation Guide

## Step 1: Install Dependencies

Before running the tool, make sure to install the required dependencies:

```bash
pip install torch transformers huggingface_hub tiktoken python-dotenv
```

## Step 2: Set Your Hugging Face Token

You have two options to set your Hugging Face token.

### Option 1: Environment Variable

You can set your Hugging Face token as an environment variable. Add the following line to your `~/.bashrc`, `~/.zshrc`, or other shell configuration file:

```bash
export HF_TOKEN='your_huggingface_token'
```

Then, source the file (e.g., `source ~/.bashrc`) or restart your terminal.

### Option 2: .env File

You can create a `.env` file in the root of the project directory and add your token there.

1.  Create a file named `.env`:
    ```bash
    touch .env
    ```
2.  Add the following line to the `.env` file:
    ```
    HF_TOKEN='your_huggingface_token'
    ```

The application will automatically load the token from this file.

## Step 3: Running the Tool

Basic usage:

```bash
python hacking.py
``` 