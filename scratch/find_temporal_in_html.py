with open("static/index.html", "r", encoding="utf-8") as f:
    lines = f.readlines()

search_ids = [
    "temporalStationBadge", "dayNightBadge", "temporalPatternStatus",
    "temporalInsightBox", "temporalExplanationText", "expTemp", "actTemp",
    "devTemp", "expPressure", "actPressure", "devPressure", "expHumidity",
    "actHumidity", "devHumidity", "temporalParamSelect", "temporalChartContainer",
    "renderTemporalChart", "fetchTemporalIntelligenceData", "TEMPORAL & SEASONAL INTELLIGENCE"
]

for idx, line in enumerate(lines, 1):
    for s_id in search_ids:
        if s_id in line:
            print(f"Line {idx}: [{s_id}] -> {line.strip()[:100]}")
