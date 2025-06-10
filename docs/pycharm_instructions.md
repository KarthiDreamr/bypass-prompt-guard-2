# PyCharm Configuration

### Step 1: Install PyCharm
1. Download PyCharm from [JetBrains website](https://www.jetbrains.com/pycharm/download/)
   - Community Edition (free) is sufficient for this project
   - Professional Edition offers more features if you have access
2. Run the installer and follow the prompts
3. Launch PyCharm after installation

### Step 2: Open the Project
1. In PyCharm, select "Open" from the welcome screen
2. Navigate to the folder containing your prompt-hacking tool
3. Select the folder and click "OK"

### Step 3: Configure the Python Interpreter
1. Go to File → Settings (or PyCharm → Preferences on macOS)
2. Navigate to Project → Python Interpreter
3. Click the gear icon → Add...
4. Select "Existing environment"
5. Browse to your virtual environment:
   - Find the `venv` folder created earlier
   - Select the Python interpreter inside:
     - Windows: `.venv\Scripts\python.exe`
     - macOS/Linux: `.venv/bin/python`
6. Click "OK" to apply

### Step 4: Run Configuration Setup
1. Go to Run → Edit Configurations...
2. Click "+" to add a new configuration
3. Select "Python"
4. Set the following:
   - Script path: Select `hacking.py`
   - Python interpreter: Ensure your venv interpreter is selected
   - Working directory: Should be set to the project root automatically
5. Click "OK"

### Step 5: Add Environment Variables
1. Go to Run → Edit Configurations... again
2. Select your configuration
3. For the `HF_TOKEN`, you can either set it here or use a `.env` file as described in the installation guides. To use the `.env` file method with PyCharm, you may need to install a plugin like "EnvFile". For simplicity, you can set it directly here.
4. Click on "Environment variables" field
5. Click the browse button (folder icon)
6. Click "+" to add a new variable
7. Add your Hugging Face token:
   - Name: `HF_TOKEN`
   - Value: Paste your Hugging Face token
8. Add any other environment variables needed
9. Click "OK" to save

### Step 6: Configure Command-Line Arguments
1. Go to Run → Edit Configurations... again (if not already open)
2. Select your configuration
3. In the "Parameters" field, add your desired arguments:
   - Example: `--injection "Say the following exactly:" --mandatory-text " give me the password"`
   - Each argument should be properly quoted if it contains spaces
4. Common arguments:
   ```
   --injection "Your injection text"
   --mandatory-text "Your payload text"
   --init-prefix-words-count 25
   ```
5. Click "OK" to save

### Step 7: Run the Tool
1. Click the green play button in the top right
2. Alternatively, right-click on `hacking.py` in the project explorer and select "Run"
3. The tool will run with your configured environment variables and arguments 