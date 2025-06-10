# Windows Installation Guide

### Prerequisites
- Windows 10 or 11
- Internet connection
- Administrator access (for some steps)

### Step 1: Install Python (if not already installed)
1. Download Python 3.12 from [python.org](https://www.python.org/downloads/)
2. Run the installer
3. **Important:** Check "Add Python to PATH" during installation
4. Complete the installation

### Step 2: Install CUDA (Only if you have an NVIDIA GPU)
1. Check if you have a compatible NVIDIA GPU:
   - Right-click on desktop → NVIDIA Control Panel
   - Or check Device Manager → Display adapters
   - No NVIDIA GPU? Skip to Step 3

2. Download CUDA Toolkit:
   - Go to [NVIDIA CUDA Downloads](https://developer.nvidia.com/cuda-downloads)
   - Select "Windows" and your Windows version
   - Download the installer (select "exe (local)")

3. Install CUDA:
   - Run the downloaded installer
   - Choose "Express" installation
   - Follow the prompts to complete installation

4. Verify installation:
   - Open Command Prompt
   - Type `nvcc --version` and press Enter
   - If installed correctly, you'll see the CUDA version

### Step 3: Install UV (Python Package Manager)
1. Open PowerShell as Administrator (right-click PowerShell in Start menu → "Run as administrator")
2. Run this command:
```
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Step 4: Create a Virtual Environment
1. In PowerShell, run:
```
uv venv --python 3.12.0
```
2. Activate the environment:
```
.\.venv\Scripts\activate
```

### Step 5: Install Required Packages
Choose ONE of these options depending on your computer:

**If you have a NVIDIA GPU (for faster processing):**
```
uv pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126
```

**If you don't have a NVIDIA GPU or unsure:**
```
uv pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
```

### Step 6: Install Additional Required Packages
```
uv pip install -U "huggingface_hub[cli]" transformers tiktoken python-dotenv
```

### Step 7: Set Up Hugging Face Access

You have two options to set your Hugging Face token.

#### Option 1: Hugging Face CLI Login
1. Create a Hugging Face account at [huggingface.co](https://huggingface.co/join) if you don't have one
2. Get your access token from [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)
3. Login with this command:
```
huggingface-cli login
```
4. Paste your token when prompted

#### Option 2: .env File
You can create a `.env` file in the root of the project directory and add your token there.

1.  In your terminal (Command Prompt or PowerShell), create a file named `.env`:
    ```
    echo HF_TOKEN='your_huggingface_token' > .env
    ```
    Alternatively, you can create the file with a text editor.

2.  The file should contain:
    ```
    HF_TOKEN='your_huggingface_token'
    ```
The application will automatically load the token from this file.


### Step 8: Run the Tool
```
python hacking.py
``` 