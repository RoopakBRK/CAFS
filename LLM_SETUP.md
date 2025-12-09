# Mistral LLM Integration - Setup Guide

## Prerequisites

1. **Python 3.8+** installed
2. **Ollama** installed and running

## Step 1: Install Ollama

### macOS
```bash
# Using Homebrew
brew install ollama

# Start Ollama service
ollama serve
```

### Linux
```bash
curl -fsSL https://ollama.com/install.sh | sh

# Start Ollama service
ollama serve
```

### Windows
Download from: https://ollama.com/download

## Step 2: Pull Mistral Model

Open a new terminal and run:
```bash
# Pull the Mistral model (default, ~4GB)
ollama pull mistral

# Or use a smaller model for faster inference
ollama pull mistral:7b-instruct
```

## Step 3: Install Python Dependencies

```bash
# From the project root
pip install -r requirements.txt
```

## Step 4: Configuration (Optional)

Create a `.env` file in the project root:
```bash
cp .env.example .env
```

Edit `.env` to customize settings:
```env
LLM_ENABLED=true          # Enable/disable LLM analysis
LLM_MODEL=mistral         # Model name (must be pulled via ollama)
LLM_TIMEOUT=30            # Timeout in seconds
LLM_TEMPERATURE=0.1       # Lower = more consistent, higher = more creative
LLM_MAX_TOKENS=500        # Maximum response length
OLLAMA_HOST=http://localhost:11434  # Ollama server URL
```

## Step 5: Test the Integration

### Start the FastAPI Server
```bash
# From project root
uvicorn app.main:app --reload
```

### Test with a Certificate
```bash
# Upload a certificate for analysis
curl -X POST "http://localhost:8000/verify" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@your_certificate.pdf"
```

## How It Works

### Traditional Analysis
The system performs three types of forensic analysis:
1. **Error Level Analysis (ELA)** - Detects inconsistent compression artifacts
2. **Noise Variance Analysis** - Identifies inconsistent noise patterns
3. **Compression Quality** - Detects multiple re-compressions

### LLM Enhancement
The Mistral LLM analyzes these metrics and provides:
- **Intelligent pattern recognition** - Identifies suspicious combinations of metrics
- **Contextual reasoning** - Explains why something looks forged or authentic
- **Confidence scoring** - Indicates how certain the LLM is about its assessment
- **Enhanced accuracy** - Catches subtle patterns rule-based systems might miss

### Combined Scoring
Final score = (Traditional Methods × 60%) + (LLM Analysis × 40%)

## Fallback Behavior

If Ollama is not available or LLM analysis fails:
- The system **continues to work** using traditional methods only
- No LLM fields are populated in the response
- A warning is logged to console

## Performance

- **Traditional analysis**: ~1-2 seconds per image
- **With LLM**: ~3-5 seconds per image (depends on model size and hardware)

## Troubleshooting

### "Ollama not available" Warning
**Cause**: Ollama service not running or model not pulled
**Solution**:
```bash
# Check if Ollama is running
curl http://localhost:11434
# If not running, start it:
ollama serve

# Check available models
ollama list
# If mistral not listed, pull it:
ollama pull mistral
```

### Slow LLM Response
**Cause**: Large model or limited hardware
**Solution**: Use a smaller model or increase timeout
```env
LLM_MODEL=mistral:7b-instruct  # Smaller, faster
LLM_TIMEOUT=60  # Longer timeout
```

### LLM Disabled
**Cause**: Missing dependencies or configuration
**Solution**: Check installation
```bash
pip install ollama
# Ensure LLM_ENABLED=true in .env or environment
```

## Advanced Configuration

### Using Different Models
```bash
# Available Mistral variants
ollama pull mistral:7b-instruct   # Smaller, faster
ollama pull mistral:latest        # Default
ollama pull mistral-small         # If available

# Update .env
LLM_MODEL=mistral:7b-instruct
```

### Adjusting Detection Sensitivity
Edit `app/agents/forensics.py` to adjust thresholds:
- Line 98: LLM confidence threshold (default 0.85)
- Line 99: LLM risk score threshold (default 0.80)
- Line 65: Combined LLM weight (default 40%)

## API Response Format

With LLM enabled, the `forensics` section includes:
```json
{
  "manipulation_score": 0.45,
  "is_high_risk": false,
  "status": "Pass - Integrity Intact",
  "details": [...],
  "llm_analysis": "Detailed technical analysis...",
  "llm_risk_score": 0.35,
  "llm_confidence": 0.82,
  "llm_reasoning": "ELA scores are moderate with uniform noise patterns..."
}
```
