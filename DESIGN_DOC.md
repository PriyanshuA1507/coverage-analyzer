# Design Document: Verification Coverage Analyzer

## 1. Architecture & Design Choices

When designing this system, I treated it as a **RAG (Retrieve-Analyze-Generate)** pipeline, but adapted for EDA data. Here is the reasoning behind my core architectural decisions.

### 1.1 Parsing: Regex vs. LLM
I decided **not** to use an LLM for the initial parsing step.
* **Why:** Coverage reports (like Ursim or Verdi) are machine-generated and highly structured. Using an LLM here introduces latency and the risk of hallucination (e.g., inventing a bin that doesn't exist).
* **Decision:** I built a strict Regex parser. It creates a "Digital Twin" of the report in JSON format. This ensures that the data fed into the AI later is 100% accurate.

### 1.2 The Prompting Strategy
To get useful test cases, context is king.
* **The Problem:** If I just ask the AI "How do I cover `fifo_full`?", it gives generic advice.
* **The Solution:** I used **Few-Shot Context Injection**. The system looks for bins in the same group that are *already covered* and feeds them to the prompt.
    * *Effect:* The prompt becomes: "The `fifo_empty` and `fifo_half` tests are passing. Suggest a test for `fifo_full` based on this context." This results in much more relevant suggestions.

### 1.3 Prioritization Logic
I treated verification time as a scarce resource. I implemented a scoring formula:
`Score = (Impact * 0.4) + (InvDifficulty * 0.3) + (Dependency * 0.3)`
This prioritizes "High Impact, Low Effort" tasks, allowing the engineer to boost coverage numbers quickly before tackling the hard corner cases.

## 2. Scalability & Future Work

The current tool works great for block-level verification. Here is how I would scale it for a full SoC with 100k+ bins.

### 2.1 Handling Complex Cross-Coverage
Multi-dimensional cross-coverage (e.g., 4-variable combinations) creates a combinatorial explosion.
* **Approach:** I would decompose these tuple strings (e.g., `<read, burst, high, error>`) into Boolean constraints.
* **Output:** Instead of English text, I would tune the LLM to output **SystemVerilog constraints** directly. This allows the verification engineer to copy-paste the output straight into their `vsequence` randomization logic.

### 2.2 Scaling to 100,000 Bins
Sending 100k API requests is slow and expensive.
* **Batching:** I would implement a clustering algorithm. If a single coverpoint has 500 missing bins, we shouldn't send 500 prompts. We should send **one** prompt summarizing the gap: *"Generate a regression strategy to cover these 500 address ranges."*
* **Semantic Caching:** I would use a vector database (like ChromaDB) to store successful test patterns. If we see a "FIFO Overflow" hole in a different block, we retrieve the solution from the cache instead of querying the LLM again.

### 2.3 The Feedback Loop
The system needs to learn.
1.  **Tagging:** Every suggestion gets a UUID.
2.  **Result Ingestion:** When the engineer runs the suggested test, we parse the regression result.
3.  **Reinforcement:** If a test fails or doesn't hit the bin, it's added as a "Negative Constraint" to future prompts (*"Don't try X, it failed last time"*).

## 3. Known Limitations
* Currently relies on text-based reports; direct integration with `.ucdb` or `.vdb` databases via vendor APIs would be faster.
* Rate limiting on the free API tier slows down large batch processing (handled via retry logic in the code).