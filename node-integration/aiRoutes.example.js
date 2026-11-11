// Add these routes to your existing query-tool router (same file as /run, /saved ...).
// Flow: question -> Python AI -> SQL -> YOUR validateReadOnlySql + runReadOnlyQuery -> rows.
//
// import { aiPost } from "../services/aiClient.js";
import { performance } from "node:perf_hooks";

router.post("/ai/report", async (req, res) => {
    const userId = getUserId(req, res);
    if (!userId) return;

    const { question, previousSql, provider, model, visualFormat = "spec" } = req.body ?? {};
    if (typeof question !== "string" || question.trim().length < 3) {
        return res.status(400).json({ error: "question is required" });
    }

    const startedAt = performance.now();
    try {
        // 1) ask the AI for SQL (only schema names go out, never data)
        let gen = await aiPost("/sql", { question, previous_sql: previousSql, provider, model });
        if (!gen.sql) {
            return res.json({
                needsClarification: true,
                question: gen.clarifying_question,
                explanation: gen.explanation,
                executionTimeMs: Number((performance.now() - startedAt).toFixed(2)),
            });
        }

        // 2) run it through the SAME safe runner you already use
        const run = (sql) => runReadOnlyQuery({
            sql, schema: "VTF", user: req.user, description: question,
            queryId: "ai-generated", clientIP: req.clientIP,
            route: req.originalUrl, reference: req.get("referer"), limit: maxSAPReturnRowLimit,
        });

        let result;
        try {
            result = await run(gen.sql);
        } catch (dbErr) {
            // 3) one automatic repair attempt using the database error text
            gen = await aiPost("/sql/fix", { sql: gen.sql, error: String(dbErr.message).slice(0, 1000), question, provider, model });
            if (!gen.sql) throw dbErr;
            result = await run(gen.sql);
        }

        const mapped = mapQueryResult(result, question, maxSAPReturnRowLimit);

        // 4) optional: ask for a chart definition using ONLY column names/types
        let visual = null;
        if (req.body.wantVisual) {
            visual = await aiPost("/visual", {
                question,
                columns: mapped.cols,           // [{name, type}] -- no rows!
                format: visualFormat,
                provider, model,
            });
        }

        return res.json({
            ...mapped,
            generatedSql: gen.sql,
            explanation: gen.explanation,
            visual,
            executionTimeMs: Number((performance.now() - startedAt).toFixed(2)),
        });
    } catch (err) {
        return handleRequestError(res, err, "AI report");
    }
});

router.post("/ai/chat", async (req, res) => {
    if (!getUserId(req, res)) return;
    try {
        const result = await aiPost("/chat", req.body);
        return res.json(result);
    } catch (err) {
        return handleRequestError(res, err, "AI chat");
    }
});
