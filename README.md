# Verification Coverage Analyzer

**Assignment  Submission**

This project is a CLI tool designed to help verification engineers close coverage gaps faster. Instead of manually staring at coverage reports to figure out what tests to write, this tool parses the report, finds the holes, and uses an LLM (Gemini 2.0) to suggest specific, actionable test scenarios.

## Project Overview

Functional coverage closure is often the bottleneck in chip verification. My goal was to build an "Assistant" that doesn't just list missing bins but actually understands *why* they might be missing based on the context of what *is* working.

### Key Features
* **Regex-Based Parsing:** I chose regex over LLMs for the parsing stage to ensure 100% accuracy and speed when handling large, rigid text reports.
* **Context-Aware Suggestions:** The agent looks at sibling bins that are already covered to "ground" its suggestions in reality, reducing hallucinations.
* **Smart Prioritization:** It doesn't just dump a list of tests; it ranks them based on how easy they are to implement and how much impact they'll have on the overall score.
* **Auto-Retry Logic:** I implemented a robust backoff strategy to handle API rate limits gracefully (crucial for the free tier!).

## Setup Instructions

### Prerequisites
* Python 3.9+
* A Google Gemini API Key

### Installation

1.  **Clone the repo:**
    ```bash
    git clone <your-repo-url>
    cd coverage_project
    ```

2.  **Set up environment:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```

3.  **Configure API Key:**
    Open `main.py` and paste your key in line 16:
    ```python
    API_KEY = "AIzaSy..."
    ```

## Usage

Simply run the main script. It includes a sample coverage report by default.

```bash
python3 main.py
