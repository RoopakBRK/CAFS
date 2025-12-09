# Quick Start Guide - Mistral LLM Integration

## ⚡ Quick Setup (5 minutes)

### Step 1: Install Ollama
```bash
# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.com/install.sh | sh

# Windows: Download from https://ollama.com/download
```

### Step 2: Start Ollama & Pull Mistral
```bash
# Terminal 1: Start Ollama server
ollama serve

# Terminal 2: Pull Mistral model
ollama pull mistral
```

### Step 3: Install Dependencies
```bash
cd /Users/roopakkrishna/Documents/newageprojects/multiagent_forgery
pip install -r requirements.txt
```

### Step 4: Test It
```bash
# Run the test script
python test_llm_integration.py

# Or start the API server
uvicorn app.main:app --reload
```

## 🎯 What You Get

### Before (Traditional Only)
- ❌ Rule-based thresholds may miss subtle patterns
- ❌ No contextual understanding
- ❌ Limited explainability

### After (With Mistral LLM)
- ✅ AI-powered pattern recognition
- ✅ Contextual analysis of metrics
- ✅ Plain-language explanations
- ✅ Confidence scoring
- ✅ 60/40 traditional+LLM hybrid approach

## 📊 Example Results

### API Response (with LLM)
```json
{
  "forensics": {
    "manipulation_score": 0.58,
    "is_high_risk": false,
    "llm_analysis": "Forensic metrics show moderate ELA with uniform noise...",
    "llm_risk_score": 0.35,
    "llm_confidence": 0.82,
    "llm_reasoning": "Authentic single-source document"
  }
}
```

## 🔧 Configuration

Optional: Create `.env` file
```bash
cp .env.example .env
```

Customize (optional):
```env
LLM_ENABLED=true
LLM_MODEL=mistral
LLM_TIMEOUT=30
```

## 🚨 Troubleshooting

### "LLM Enabled: False"
```bash
# Check Ollama is running
curl http://localhost:11434

# If not, start it:
ollama serve

# Check model is installed
ollama list

# If mistral not listed:
ollama pull mistral
```

### Still Not Working?
Check [LLM_SETUP.md](file:///Users/roopakkrishna/Documents/newageprojects/multiagent_forgery/LLM_SETUP.md) for detailed troubleshooting.

## 📁 Files Overview

- **forensics.py** - Enhanced with LLM analysis
- **config.py** - LLM configuration
- **schemas.py** - Extended with LLM fields
- **test_llm_integration.py** - Test script
- **LLM_SETUP.md** - Detailed setup guide

## ✅ Verification

1. ✅ Code compiles without errors
2. ✅ Imports work correctly  
3. ✅ Graceful fallback when LLM unavailable
4. ✅ Test script ready

## 🎓 Next Steps

1. Start Ollama and pull Mistral model
2. Run `python test_llm_integration.py`
3. Test with your certificates
4. Enjoy enhanced accuracy! 🎉
