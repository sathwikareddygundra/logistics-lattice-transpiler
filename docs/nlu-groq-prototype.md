# NLU prototype: hosted LLM (openai/gpt-oss-20b) vs the rule parser

Sample: 20 labeled queries (every nth row of nlu/data/labeled_queries.jsonl).
- Intent correct: 15/20
- Exact entity match: 13/20
- Latency p50 1109 ms, max 3134 ms

| query | want | intent ok | exact | ms | note |
|---|---|---|---|---|---|
| What is the total freight cost in July 2026? | aggregation | True | True | 688 |  |
| average unloading time by origin warehouse | aggregation | True | True | 614 |  |
| average TAT for FedEx in August | aggregation | True | True | 945 |  |
| average TAT for delayed shipments by carrier | aggregation | True | True | 1229 |  |
| total freight cost for the last 30 days | aggregation | True | True | 882 |  |
| how many shipments from Atlanta to Houston | aggregation | True | False | 988 | got aggregation ['agg:count', 'filter:destination_city=Houston', 'filter:origin_warehouse=Atlanta', 'metric:invoice_number'] |
| average weight by carrier for Chicago in July 2026 | aggregation | True | True | 710 |  |
| average TAT by sla status | aggregation | True | True | 1018 |  |
| which carrier has the most delayed shipments | rank | True | True | 1200 |  |
| top 10 destinations by freight cost in July 2026 | rank | True | True | 865 |  |
| daily shipments in August 2026 | trend | False | False | 1865 | error: Groq API call failed with status 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organiza |
| trend of average loading time by month | trend | True | True | 2867 |  |
| forecast number of shipments next 3 months | forecast | False | False | 1645 | error: Groq API call failed with status 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organiza |
| forecast loading time next 3 months | forecast | True | True | 2623 |  |
| compare average TAT between MCW and VGU | comparison | False | False | 1749 | error: Groq API call failed with status 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organiza |
| compare weight between MCW and YCW | comparison | True | True | 465 |  |
| show DHL shipments for MCW | filter | True | True | 766 |  |
| show on time shipments from Atlanta | join | True | False | 3134 | got join ['filter:origin_warehouse=Atlanta', 'filter:sla_status=On Time'] |
| display XPO shipments in June 2026 | filter | False | False | 1687 | error: Groq API call failed with status 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organiza |
| show delayed UPS shipments | join | False | False | 1867 | error: Groq API call failed with status 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organiza |
