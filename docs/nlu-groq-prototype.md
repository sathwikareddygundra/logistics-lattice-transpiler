# NLU prototype: hosted LLM (openai/gpt-oss-20b) vs the rule parser

Sample: 20 labeled queries (every nth row of nlu/data/labeled_queries.jsonl).
- Intent correct: 5/20
- Exact entity match: 5/20
- Latency p50 1800 ms, max 2981 ms

| query | want | intent ok | exact | ms | note |
|---|---|---|---|---|---|
| What is the total freight cost in July 2026? | aggregation | True | True | 840 |  |
| average unloading time by origin warehouse | aggregation | True | True | 1097 |  |
| average TAT for FedEx in August | aggregation | True | True | 1061 |  |
| average TAT for delayed shipments by carrier | aggregation | False | False | 1795 | error: Groq API call failed with status 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organiza |
| total freight cost for the last 30 days | aggregation | False | False | 1793 | error: Groq API call failed with status 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organiza |
| how many shipments from Atlanta to Houston | aggregation | False | False | 1907 | error: Groq API call failed with status 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organiza |
| average weight by carrier for Chicago in July 2026 | aggregation | False | False | 1871 | error: Groq API call failed with status 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organiza |
| average TAT by sla status | aggregation | False | False | 1875 | error: Groq API call failed with status 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organiza |
| which carrier has the most delayed shipments | rank | False | False | 1744 | error: Groq API call failed with status 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organiza |
| top 10 destinations by freight cost in July 2026 | rank | True | True | 1733 |  |
| daily shipments in August 2026 | trend | False | False | 1720 | error: Groq API call failed with status 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organiza |
| trend of average loading time by month | trend | False | False | 1804 | error: Groq API call failed with status 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organiza |
| forecast number of shipments next 3 months | forecast | False | False | 1882 | error: Groq API call failed with status 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organiza |
| forecast loading time next 3 months | forecast | False | False | 1872 | error: Groq API call failed with status 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organiza |
| compare average TAT between MCW and VGU | comparison | False | False | 1955 | error: Groq API call failed with status 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organiza |
| compare weight between MCW and YCW | comparison | False | False | 2001 | error: Groq API call failed with status 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organiza |
| show DHL shipments for MCW | filter | False | False | 1794 | error: Groq API call failed with status 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organiza |
| show on time shipments from Atlanta | join | False | False | 1761 | error: Groq API call failed with status 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organiza |
| display XPO shipments in June 2026 | filter | False | False | 1993 | error: Groq API call failed with status 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organiza |
| show delayed UPS shipments | join | True | True | 2981 |  |
