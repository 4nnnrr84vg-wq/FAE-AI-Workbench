"use client";

import { useEffect, useMemo, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

type Source = {
  path: string;
  line?: number;
  title?: string;
  snippet?: string;
  score?: number;
  chunk_id?: string;
  retrieval?: string;
  matched_issue?: string;
};

type RagStatus = {
  enabled: boolean;
  qdrant_ok: boolean;
  collection: string;
  collection_exists: boolean;
  indexed_points: number;
  indexed_files: number;
  embedding_mode: string;
  vector_size: number;
  last_error: string;
};

type Health = {
  ok: boolean;
  model_api: boolean;
  knowledge_root_exists: boolean;
  gitlab_sdk_configured?: boolean;
  rag?: RagStatus;
};

type SdkVersionInfo = {
  enabled: boolean;
  configured: boolean;
  version: string;
  ref: string;
  ref_type: string;
  commit_sha: string;
  commit_title: string;
  web_url: string;
  release_notes: string;
  matched_files: string[];
  error: string;
};

type Issue = {
  customer: string;
  product_model: string;
  sdk_version: string;
  firmware_version: string;
  hardware_model: string;
  symptom: string;
  error_keywords: string[];
  attachments: string[];
  missing_info: string[];
  priority: string;
  suggested_owner: string;
  raw_text: string;
  confidence: number;
};

type Knowledge = {
  answer: string;
  sources: Source[];
  query_terms: string[];
  used_llm: boolean;
  retrieval_mode?: string;
  index_status?: RagStatus;
  sdk_info?: SdkVersionInfo;
};

type LogAnalysis = {
  key_error_lines: string[];
  error_codes: string[];
  module_owner: string;
  timeline: string[];
  contexts: Array<{ line: number; before: string[]; current: string; after: string[] }>;
  hypotheses: string[];
  missing_info: string[];
  related_docs: Source[];
  checklist: string[];
  disclaimer: string;
};

type ResponseDraft = {
  draft: string;
  follow_up_questions: string[];
  sources: Source[];
  used_llm: boolean;
};

type Ticket = {
  title: string;
  severity: string;
  suggested_owner: string;
  report: string;
  fields: Record<string, unknown>;
  sources: Source[];
};

const sampleCustomer = `客户：某客户
型号：XC6517
SDK v2.3.1，固件 1.8.0
升级固件后无法联网，日志里看到 WIFI_ERR_INIT_FAILED，已附 boot.log 和截图。`;

const sampleLog = `[00:00:01.112] boot start
[00:00:03.410] sdk version v2.3.1
[00:00:05.002] wifi init start
[00:00:05.351] ERROR WIFI_ERR_INIT_FAILED wifi init failed
[00:00:05.777] retry wifi init timeout`;

async function postJson<T>(path: string, payload: unknown): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!resp.ok) {
    const detail = await resp.text();
    throw new Error(`${resp.status} ${resp.statusText}: ${detail}`);
  }
  return resp.json();
}

export default function Home() {
  const [customerText, setCustomerText] = useState(sampleCustomer);
  const [logText, setLogText] = useState(sampleLog);
  const [customerHint, setCustomerHint] = useState("");
  const [question, setQuestion] = useState("v2.3.1 升级后无法联网怎么排查？");
  const [sdkVersion, setSdkVersion] = useState("");
  const [attachments, setAttachments] = useState("boot.log,screenshot.png");
  const [projectPath, setProjectPath] = useState("");

  const [health, setHealth] = useState<Health | null>(null);
  const [ragStatus, setRagStatus] = useState<RagStatus | null>(null);
  const [issue, setIssue] = useState<Issue | null>(null);
  const [knowledge, setKnowledge] = useState<Knowledge | null>(null);
  const [logAnalysis, setLogAnalysis] = useState<LogAnalysis | null>(null);
  const [responseDraft, setResponseDraft] = useState<ResponseDraft | null>(null);
  const [ticket, setTicket] = useState<Ticket | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const attachmentList = useMemo(
    () => attachments.split(",").map((item) => item.trim()).filter(Boolean),
    [attachments]
  );

  useEffect(() => {
    fetch(`${API_BASE}/health`)
      .then((resp) => resp.json())
      .then((data: Health) => {
        setHealth(data);
        if (data.rag) setRagStatus(data.rag);
      })
      .catch((err) => setError(`后端连接失败：${err.message}`));
  }, []);

  async function runStep<T>(label: string, fn: () => Promise<T>): Promise<T | null> {
    setBusy(label);
    setError("");
    try {
      return await fn();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return null;
    } finally {
      setBusy("");
    }
  }

  async function parseInbox(): Promise<Issue | null> {
    return runStep("整理客户问题", async () => {
      const data = await postJson<Issue>("/api/inbox/parse", {
        text: customerText,
        customer_hint: customerHint,
        attachments: attachmentList
      });
      setIssue(data);
      return data;
    });
  }

  async function queryKb(baseIssue?: Issue | null): Promise<Knowledge | null> {
    const usedIssue = baseIssue || issue;
    return runStep("检索资料库", async () => {
      const data = await postJson<Knowledge>("/api/kb/query", {
        question: question || usedIssue?.symptom || customerText,
        product_model: usedIssue?.product_model || "",
        sdk_version: sdkVersion || usedIssue?.sdk_version || "",
        firmware_version: usedIssue?.firmware_version || "",
        project_path: projectPath,
        top_k: 8
      });
      setKnowledge(data);
      if (data.index_status) setRagStatus(data.index_status);
      return data;
    });
  }

  async function reindexKb(): Promise<void> {
    await runStep("重建资料索引", async () => {
      const data = await postJson<{ ok: boolean; status: RagStatus; message: string }>("/api/kb/reindex", {
        force: true
      });
      setRagStatus(data.status);
      return data;
    });
  }

  async function analyzeLog(baseIssue?: Issue | null): Promise<LogAnalysis | null> {
    const usedIssue = baseIssue || issue;
    return runStep("分析日志", async () => {
      const data = await postJson<LogAnalysis>("/api/logs/analyze", {
        log_text: logText || customerText,
        product_model: usedIssue?.product_model || "",
        sdk_version: usedIssue?.sdk_version || "",
        firmware_version: usedIssue?.firmware_version || "",
        top_k_sources: 6
      });
      setLogAnalysis(data);
      return data;
    });
  }

  async function draftReply(): Promise<ResponseDraft | null> {
    return runStep("生成客户回复", async () => {
      const usedIssue = issue || (await parseInbox());
      if (!usedIssue) throw new Error("缺少客户问题结构化结果");
      const data = await postJson<ResponseDraft>("/api/responses/draft", {
        issue: usedIssue,
        log_analysis: logAnalysis,
        knowledge
      });
      setResponseDraft(data);
      return data;
    });
  }

  async function generateTicket(): Promise<Ticket | null> {
    return runStep("生成内部工单", async () => {
      const usedIssue = issue || (await parseInbox());
      if (!usedIssue) throw new Error("缺少客户问题结构化结果");
      const data = await postJson<Ticket>("/api/tickets/generate", {
        issue: usedIssue,
        log_analysis: logAnalysis,
        knowledge
      });
      setTicket(data);
      return data;
    });
  }

  async function runAll() {
    await runStep("一键初筛", async () => {
      const data = await postJson<{
        issue: Issue;
        knowledge: Knowledge;
        log_analysis: LogAnalysis;
        response: ResponseDraft;
        ticket: Ticket;
      }>("/api/workbench/run", {
        customer_text: customerText,
        log_text: logText,
        customer_hint: customerHint,
        attachments: attachmentList,
        question,
        project_path: projectPath,
        sdk_version: sdkVersion
      });
      setIssue(data.issue);
      setKnowledge(data.knowledge);
      if (data.knowledge.index_status) setRagStatus(data.knowledge.index_status);
      setLogAnalysis(data.log_analysis);
      setResponseDraft(data.response);
      setTicket(data.ticket);
      return data;
    });
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <h1>FAE AI Workbench</h1>
          <p>客户问题、资料检索、日志初筛、回复草稿、内部工单</p>
        </div>
        <div className="statusRow">
          <Status label="API" ok={!error && Boolean(health)} />
          <Status label="模型" ok={Boolean(health?.model_api)} muted={!health} />
          <Status label="资料库" ok={Boolean(health?.knowledge_root_exists)} muted={!health} />
          <Status label="GitLab SDK" ok={Boolean(health?.gitlab_sdk_configured)} muted={!health} />
          <Status label="向量索引" ok={Boolean(ragStatus?.qdrant_ok && ragStatus.indexed_points > 0)} muted={!ragStatus} />
          <button className="smallButton" onClick={reindexKb} disabled={Boolean(busy)}>重建索引</button>
        </div>
      </header>

      {error ? <div className="errorBar">{error}</div> : null}
      {busy ? <div className="busyBar">处理中：{busy}</div> : null}

      <section className="workspace">
        <section className="panel inputPanel">
          <div className="panelTitle">
            <h2>输入</h2>
            <button onClick={runAll} disabled={Boolean(busy)}>一键初筛</button>
          </div>

          <label>
            客户名称
            <input value={customerHint} onChange={(event) => setCustomerHint(event.target.value)} placeholder="可选" />
          </label>

          <label>
            客户消息 / 群聊上下文
            <textarea value={customerText} onChange={(event) => setCustomerText(event.target.value)} rows={9} />
          </label>

          <label>
            附件名
            <input value={attachments} onChange={(event) => setAttachments(event.target.value)} placeholder="boot.log,screenshot.png" />
          </label>

          <label>
            资料检索问题
            <input value={question} onChange={(event) => setQuestion(event.target.value)} />
          </label>

          <label>
            SDK 版本
            <input value={sdkVersion} onChange={(event) => setSdkVersion(event.target.value)} placeholder="可选，例如 v2.3.1" />
          </label>

          <label>
            本地工程路径
            <input
              value={projectPath}
              onChange={(event) => setProjectPath(event.target.value)}
              placeholder="可选，例如 D:\\433_jixiang"
            />
          </label>

          <label>
            设备日志
            <textarea value={logText} onChange={(event) => setLogText(event.target.value)} rows={10} />
          </label>

          <div className="actionGrid">
            <button onClick={parseInbox} disabled={Boolean(busy)}>整理问题</button>
            <button onClick={() => queryKb()} disabled={Boolean(busy)}>查资料库</button>
            <button onClick={() => analyzeLog()} disabled={Boolean(busy)}>分析日志</button>
            <button onClick={draftReply} disabled={Boolean(busy)}>客户回复</button>
            <button onClick={generateTicket} disabled={Boolean(busy)}>内部工单</button>
          </div>
        </section>

        <section className="panel">
          <div className="panelTitle">
            <h2>分析</h2>
            <span className="subtle">规则优先，资料可追溯</span>
          </div>
          <IssueView issue={issue} />
          <Block title="资料库">
            {knowledge ? (
              <>
                <RagInfo knowledge={knowledge} status={ragStatus} />
                <p className="answerText">{knowledge.answer}</p>
                <TagRow items={knowledge.query_terms} />
                <Sources sources={knowledge.sources} />
              </>
            ) : (
              <Empty text="尚未检索资料库" />
            )}
          </Block>
          <Block title="日志初筛">
            {logAnalysis ? (
              <>
                <Field label="模块归属" value={logAnalysis.module_owner} />
                <List title="关键错误行" items={logAnalysis.key_error_lines} />
                <List title="错误码" items={logAnalysis.error_codes} compact />
                <List title="初步假设" items={logAnalysis.hypotheses} />
                <List title="FAE 检查清单" items={logAnalysis.checklist} />
              </>
            ) : (
              <Empty text="尚未分析日志" />
            )}
          </Block>
        </section>

        <section className="panel outputPanel">
          <div className="panelTitle">
            <h2>输出</h2>
            <span className="subtle">发客户 / 给研发</span>
          </div>
          <Block title="客户回复草稿">
            {responseDraft ? (
              <>
                <textarea className="readonlyText" value={responseDraft.draft} readOnly rows={12} />
                <List title="需补充信息" items={responseDraft.follow_up_questions} compact />
              </>
            ) : (
              <Empty text="尚未生成客户回复" />
            )}
          </Block>
          <Block title="内部工单报告">
            {ticket ? (
              <>
                <div className="ticketHead">
                  <strong>{ticket.title}</strong>
                  <span>{ticket.suggested_owner}</span>
                </div>
                <pre className="report">{ticket.report}</pre>
              </>
            ) : (
              <Empty text="尚未生成内部工单" />
            )}
          </Block>
        </section>
      </section>
    </main>
  );
}

function Status({ label, ok, muted = false }: { label: string; ok: boolean; muted?: boolean }) {
  return <span className={`status ${muted ? "muted" : ok ? "ok" : "bad"}`}>{label}</span>;
}

function RagInfo({ knowledge, status }: { knowledge: Knowledge; status: RagStatus | null }) {
  const mode = knowledge.retrieval_mode || "unknown";
  const points = knowledge.index_status?.indexed_points ?? status?.indexed_points ?? 0;
  const error = knowledge.index_status?.last_error || status?.last_error || "";
  const sdk = knowledge.sdk_info;
  return (
    <div className="ragInfo">
      <span>检索：{mode}</span>
      <span>AI总结：{knowledge.used_llm ? "已使用" : "未使用"}</span>
      <span>索引片段：{points}</span>
      {sdk?.version ? <span>SDK：{sdk.enabled ? `${sdk.ref_type} ${sdk.ref}` : sdk.error || "未关联"}</span> : null}
      {error ? <span className="ragError">{error}</span> : null}
    </div>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="block">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="empty">{text}</p>;
}

function Field({ label, value }: { label: string; value?: string }) {
  return (
    <div className="field">
      <span>{label}</span>
      <strong>{value || "未识别"}</strong>
    </div>
  );
}

function IssueView({ issue }: { issue: Issue | null }) {
  if (!issue) {
    return (
      <Block title="客户问题结构化">
        <Empty text="尚未整理客户问题" />
      </Block>
    );
  }
  return (
    <Block title="客户问题结构化">
      <div className="fieldGrid">
        <Field label="客户" value={issue.customer} />
        <Field label="产品型号" value={issue.product_model} />
        <Field label="SDK" value={issue.sdk_version} />
        <Field label="固件" value={issue.firmware_version} />
        <Field label="优先级" value={issue.priority} />
        <Field label="负责模块" value={issue.suggested_owner} />
      </div>
      <p className="symptom">{issue.symptom}</p>
      <TagRow items={issue.error_keywords} />
      <List title="缺失信息" items={issue.missing_info} compact />
    </Block>
  );
}

function TagRow({ items }: { items: string[] }) {
  if (!items?.length) return null;
  return (
    <div className="tags">
      {items.map((item) => (
        <span key={item}>{item}</span>
      ))}
    </div>
  );
}

function List({ title, items, compact = false }: { title: string; items: string[]; compact?: boolean }) {
  if (!items?.length) return null;
  return (
    <div className={compact ? "list compact" : "list"}>
      <h4>{title}</h4>
      <ul>
        {items.map((item, idx) => (
          <li key={`${title}-${idx}`}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function Sources({ sources }: { sources: Source[] }) {
  if (!sources?.length) return null;
  return (
    <div className="sources">
      <h4>资料来源</h4>
      {sources.slice(0, 6).map((source, idx) => (
        <div key={`${source.path}-${source.line}-${idx}`} className="source">
          <strong>{source.title || source.path}</strong>
          <span>{source.retrieval ? ` ${source.retrieval}` : ""}{source.line ? ` 第 ${source.line} 行` : ""}</span>
          {source.matched_issue ? <p className="sourceIssue">对应问题：{source.matched_issue}</p> : null}
          <p>{source.snippet}</p>
        </div>
      ))}
    </div>
  );
}
