import re
import json
import time
import random
from google import genai

# CONFIGURATION 
API_KEY = "YOUR_GEMINI_KEY_HERE"  # Keep this here for grading, even if using mock
USE_MOCK_MODE = False              # Set to False to use real AI

# Initialize Client
client = genai.Client(api_key=API_KEY)
MODEL_NAME = "gemini-2.0-flash"

# MOCK DATA GENERATOR 
def get_mock_response(target_bin):
    """Returns realistic AI responses for the sample report bins."""
    mocks = {
        "cg_transfer_size.cp_size.max[4096]": {
            "suggestion": "Configure DMA transfer size to exactly 4096 bytes. Ensure source/dest buffers are large enough.",
            "difficulty": "easy",
            "dependencies": ["Buffer size > 4KB"],
            "test_outline": ["1. Alloc 5KB src/dst buffers", "2. Set transfer_size=4096", "3. Start DMA", "4. Check EOT"]
        },
        "cg_transfer_size.cp_burst_type.wrap": {
            "suggestion": "Configure DMA for WRAP burst type. Align address to wrap boundary.",
            "difficulty": "medium",
            "dependencies": ["AXI Slave support"],
            "test_outline": ["1. Set burst_type=WRAP", "2. Set addr=0x1FFC", "3. Set len=4", "4. Verify address wraps to 0x1000"]
        },
        "cg_channel_arbitration.cp_active_channels.three_channels": {
            "suggestion": "Activate exactly 3 channels simultaneously with different priorities.",
            "difficulty": "medium",
            "dependencies": [],
            "test_outline": ["1. Config Ch0, Ch1, Ch2", "2. Enable all 3", "3. Verify concurrent operation"]
        },
        "cg_channel_arbitration.cp_error_type.decode_error": {
            "suggestion": "Program DMA to access an unmapped memory region to trigger DECERR.",
            "difficulty": "hard",
            "dependencies": ["Memory Map knowledge"],
            "test_outline": ["1. Find unmapped addr", "2. Set DMA src=unmapped", "3. Check error status reg"]
        }
    }
    
    # Return specific mock or a generic fallback
    defaults = {
        "suggestion": "Generic test suggestion for this bin.",
        "difficulty": "medium",
        "dependencies": [],
        "test_outline": ["1. Setup", "2. Run", "3. Verify"]
    }
    return mocks.get(target_bin, defaults)

# PART 1: PARSER 
class CoverageParser:
    def parse(self, report_text):
        data = {
            "design": "unknown",
            "overall_coverage": 0.0,
            "covergroups": [],
            "uncovered_bins": [],  
            "cross_coverage": []   
        }
        
        rx_design = re.compile(r"Design:\s+(.+)")
        rx_overall = re.compile(r"Overall Coverage:\s+([\d\.]+)%")
        rx_cg = re.compile(r"Covergroup:\s+(\w+)")
        rx_cg_cov = re.compile(r"Coverage:\s+([\d\.]+)%")
        rx_cp = re.compile(r"Coverpoint:\s+(\w+)")
        rx_cross = re.compile(r"Cross Coverage:\s+(\w+)")
        rx_bin = re.compile(r"bin\s+(\w+)(?:\s+(\[.*?\]))?")
        rx_cross_bin = re.compile(r"<(.+)>")
        rx_hits = re.compile(r"hits:\s+(\d+)")
        
        current_cg = None
        current_cp = None
        current_cross = None
        
        lines = report_text.split('\n')
        iterator = iter(lines)
        
        for line in iterator:
            line = line.strip()
            
            if m := rx_design.search(line): data["design"] = m.group(1)
            elif m := rx_overall.search(line): data["overall_coverage"] = float(m.group(1))
            
            elif m := rx_cg.search(line):
                current_cg = { "name": m.group(1), "coverage": 0.0, "coverpoints": [] }
                data["covergroups"].append(current_cg)
                current_cp = None
                current_cross = None
                
            elif current_cg and (m := rx_cg_cov.search(line)):
                if current_cross: current_cross["coverage"] = float(m.group(1))
                else: current_cg["coverage"] = float(m.group(1))
                
            elif current_cg and (m := rx_cp.search(line)):
                current_cp = {"name": m.group(1), "bins": []}
                current_cg["coverpoints"].append(current_cp)
                current_cross = None
                
            elif current_cg and (m := rx_cross.search(line)):
                current_cross = {"name": m.group(1), "coverage": 0.0, "uncovered": []}
                data["cross_coverage"].append(current_cross)
                current_cp = None
                
            elif current_cp and (m := rx_bin.search(line)):
                bin_name = m.group(1)
                bin_range = m.group(2) if m.group(2) else ""
                bin_data = { "name": bin_name, "range": bin_range, "hits": 0, "covered": False }
                
                try:
                    next_line = next(iterator).strip()
                    if h := rx_hits.search(next_line):
                        bin_data["hits"] = int(h.group(1))
                        bin_data["covered"] = bin_data["hits"] > 0
                except StopIteration: pass
                
                current_cp["bins"].append(bin_data)
                
                if not bin_data["covered"]:
                    full_name = f"{bin_name}{bin_range}"
                    data["uncovered_bins"].append({
                        "covergroup": current_cg["name"],
                        "coverpoint": current_cp["name"],
                        "bin": full_name
                    })

            elif current_cross and (m := rx_cross_bin.search(line)):
                bin_name = f"<{m.group(1)}>"
                is_covered = False
                try:
                    next_line = next(iterator).strip()
                    if h := rx_hits.search(next_line):
                        hits = int(h.group(1))
                        is_covered = hits > 0
                except StopIteration: pass
                
                if not is_covered:
                    current_cross["uncovered"].append(bin_name)
                
        return data

#  PART 2: LLM AGENT 
class CoverageAgent:
    def generate_prompt(self, design, bin_info, context_bins):
        return f"""
        You are a Verification Engineer. Analyze this coverage hole for IP: {design}.
        TARGET UNCOVERED BIN: {bin_info}
        
        CONTEXT - ALREADY COVERED (Use as reference):
        {', '.join(context_bins[:5])}
        
        TASK:
        1. Suggest a specific test scenario.
        2. Estimate difficulty (easy/medium/hard).
        3. List dependencies.
        
        IMPORTANT: Respond ONLY with a raw JSON object (no markdown).
        Structure: {{ "suggestion": "...", "test_outline": ["step1"], "dependencies": ["..."], "difficulty": "medium", "reasoning": "..." }}
        """

    def generate_with_retry(self, prompt, retries=3):
        """Attempts to generate content, waiting if rate limited."""
        for attempt in range(retries):
            try:
                response = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=prompt
                )
                return response
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    wait_time = 15 * (attempt + 1)
                    print(f"   [Rate Limit] Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                else:
                    raise e
        return None

    def get_suggestions(self, report_data):
        suggestions = []
        
        for hole in report_data["uncovered_bins"]:
            target_id = f"{hole['covergroup']}.{hole['coverpoint']}.{hole['bin']}"
            context = ["related_bin_A", "related_bin_B"] 
            
            print(f"[AI] Analyzing {target_id}...")
            
            if USE_MOCK_MODE:
                # Bypass API completely
                mock_data = get_mock_response(target_id)
                suggestions.append({
                    "target_bin": target_id,
                    "priority": "pending",
                    "difficulty": mock_data["difficulty"],
                    "suggestion": mock_data["suggestion"],
                    "test_outline": mock_data["test_outline"],
                    "dependencies": mock_data["dependencies"],
                    "reasoning": "Mocked reasoning for demo purposes."
                })
                time.sleep(0.1) # Fast simulation
            else:
                # Real API Logic
                prompt = self.generate_prompt(report_data["design"], target_id, context)
                time.sleep(2) 
                
                try:
                    response = self.generate_with_retry(prompt)
                    if response:
                        text_content = response.text
                        if "```json" in text_content:
                            text_content = text_content.replace("```json", "").replace("```", "")
                        
                        ai_data = json.loads(text_content)
                        suggestions.append({
                            "target_bin": target_id,
                            "priority": "pending",
                            "difficulty": ai_data.get("difficulty", "medium"),
                            "suggestion": ai_data.get("suggestion", ""),
                            "test_outline": ai_data.get("test_outline", []),
                            "dependencies": ai_data.get("dependencies", []),
                            "reasoning": ai_data.get("reasoning", "")
                        })
                    else:
                        print(f"   [Skipped] Could not process after retries.")
                except Exception as e:
                    print(f"[API Error] Failed to process {target_id}: {e}")
                            
        return suggestions

#  PART 3: PRIORITIZATION 
def prioritize(suggestions):
    for s in suggestions:
        diff_map = {"easy": 1.0, "medium": 2.0, "hard": 3.0}
        diff_val = diff_map.get(str(s["difficulty"]).lower(), 2.0)
        inv_difficulty = 1.0 / diff_val
        dep_score = 1.0 if not s["dependencies"] else 0.5
        
        s["score"] = (1.0 * 0.4) + (inv_difficulty * 0.3) + (dep_score * 0.3)
        
        if s["score"] > 0.7: s["priority"] = "high"
        elif s["score"] > 0.4: s["priority"] = "medium"
        else: s["priority"] = "low"
        
    return sorted(suggestions, key=lambda x: x["score"], reverse=True)

#  PART 4: BONUS PREDICTION 
def predict_closure(report_data):
    blocking_bins = len(report_data["uncovered_bins"]) 
    cross_holes = sum(len(c["uncovered"]) for c in report_data["cross_coverage"])
    
    total_complexity = blocking_bins + (cross_holes * 2)
    hours = total_complexity * 4
    days = hours / 8
    
    print("\n--- Part 4: Closure Prediction ---")
    print(f"1. Estimated Time: {days:.1f} days ({hours} hours)")
    print(f"2. Closure Probability: {100.0 if hours < 40 else 60.0}%")
    print(f"3. Blocking Bins: {blocking_bins} standard + {cross_holes} cross-coverage")

#  MAIN EXECUTION 
if __name__ == "__main__":
    sample_report = """
Design: dma_controller
Date: 2025-01-02
Overall Coverage: 54.84%
Covergroup: cg_transfer_size
Coverage: 75.00%
Coverpoint: cp_size
bin small [0:255]
hits: 1523
covered
bin medium [256:1023]
hits: 892
covered
bin max [4096]
hits: 0
UNCOVERED
Coverpoint: cp_burst_type
bin single
hits: 2341
covered
bin incr
hits: 1822
covered
bin wrap
hits: 0
UNCOVERED
bin fixed
hits: 234
covered
Covergroup: cg_channel_arbitration
Coverage: 60.00% (3/5 bins)
Coverpoint: cp_active_channels
bin one_channel hits: 5000 covered
bin two_channels hits: 1200 covered
bin three_channels hits: 45 covered
bin four_channels hits: 0 UNCOVERED
bin all_eight hits: 0 UNCOVERED
Covergroup: cg_error_scenarios
Coverage: 33.33% (2/6 bins)
Coverpoint: cp_error_type
bin no_error hits: 10000 covered
bin slave_error hits: 1200 covered
bin decode_error hits: 0 UNCOVERED
bin timeout hits: 0 UNCOVERED
Coverpoint: cp_error_recovery
bin retry_success hits: 0 UNCOVERED
bin abort hits: 0 UNCOVERED
Cross Coverage: cross_size_burst
Coverage: 50.00% (6/12 bins)
<small, single> hits: 500 covered
<small, incr> hits: 400 covered
<small, wrap> hits: 0 UNCOVERED
    """

    print("1. Parsing Report ")
    parser = CoverageParser()
    report = parser.parse(sample_report)
    print(json.dumps(report, indent=2))
    
    print("\n 2. Generating Suggestions (Mock Mode) ")
    if "YOUR_GEMINI_KEY" in API_KEY:
        print("ERROR: Please insert your API Key in line 16 of main.py")
    else:
        agent = CoverageAgent()
        suggestions = agent.get_suggestions(report)
        
        print("\n 3. Prioritized Plan ")
        ranked = prioritize(suggestions)
        print(json.dumps({"suggestions": ranked}, indent=2))
        
        predict_closure(report)

        
