import * as vscode from "vscode";
import * as cp from "child_process";
import { chatCompletion, LLMConfig } from "./llm";
import { StatusBar } from "./statusbar";

interface ReviewComment {
  path: string;
  line: number;
  body: string;
  severity: string;
}

interface ReviewResult {
  summary: string;
  riskLevel: string;
  comments: ReviewComment[];
  costUsd: number;
  model: string;
}

const SYSTEM_PROMPT = `You are an expert code reviewer. Review the provided code with precision.

## Your principles:
1. Be precise — reference specific line numbers.
2. Be actionable — suggest fixes with code examples.
3. Be concise — one clear sentence per issue.
4. Prioritize — Security > Correctness > Performance > Design > Style.
5. Don't nitpick — skip formatting and anything a linter handles.

## What to look for:
- Bugs: logic errors, off-by-one, null handling, race conditions, resource leaks
- Security: injection, auth bypass, secrets in code, unsafe deserialization
- Performance: N+1 queries, missing indexes, unnecessary allocations
- Design: breaking contracts, missing error handling, tight coupling

## What to SKIP:
- Style issues (formatting, naming)
- Missing type hints where types are obvious
- Adding comments to self-documenting code`;

function getConfig(): LLMConfig {
  const config = vscode.workspace.getConfiguration("aiCodeReviewer");
  return {
    provider: config.get<string>("provider") ?? "openai",
    model: config.get<string>("model") ?? "",
    apiKey: config.get<string>("apiKey") ?? "",
    apiBaseUrl: config.get<string>("apiBaseUrl") ?? "",
  };
}

function getReviewSettings(): { style: string; maxComments: number; language: string; customInstructions: string } {
  const config = vscode.workspace.getConfiguration("aiCodeReviewer");
  return {
    style: config.get<string>("reviewStyle") ?? "concise",
    maxComments: config.get<number>("maxComments") ?? 15,
    language: config.get<string>("language") ?? "en",
    customInstructions: config.get<string>("customInstructions") ?? "",
  };
}

function severityToDiagnosticSeverity(severity: string): vscode.DiagnosticSeverity {
  switch (severity) {
    case "critical":
      return vscode.DiagnosticSeverity.Error;
    case "warning":
      return vscode.DiagnosticSeverity.Warning;
    case "suggestion":
      return vscode.DiagnosticSeverity.Information;
    default:
      return vscode.DiagnosticSeverity.Hint;
  }
}

function parseReviewResponse(content: string): ReviewResult {
  try {
    const jsonMatch = content.match(/\{[\s\S]*\}/);
    if (!jsonMatch) {
      return { summary: content.substring(0, 500), riskLevel: "medium", comments: [], costUsd: 0, model: "" };
    }
    const data = JSON.parse(jsonMatch[0]);
    return {
      summary: data.summary ?? "",
      riskLevel: data.risk_level ?? "medium",
      comments: (data.comments ?? []).map((c: Record<string, unknown>) => ({
        path: (c.path as string) ?? "",
        line: (c.line as number) ?? 0,
        body: (c.body as string) ?? "",
        severity: (c.severity as string) ?? "info",
      })),
      costUsd: 0,
      model: "",
    };
  } catch {
    return { summary: content.substring(0, 500), riskLevel: "medium", comments: [], costUsd: 0, model: "" };
  }
}

function getGitDiff(cwd: string): Promise<string> {
  return new Promise((resolve, reject) => {
    cp.exec(
      "git diff HEAD",
      { cwd, maxBuffer: 1024 * 1024 * 5 },
      (err, stdout) => {
        if (err) {
          // Try unstaged diff
          cp.exec(
            "git diff",
            { cwd, maxBuffer: 1024 * 1024 * 5 },
            (err2, stdout2) => {
              if (err2) {
                reject(new Error("Not a git repository or git not found"));
              } else {
                resolve(stdout2);
              }
            }
          );
        } else {
          resolve(stdout);
        }
      }
    );
  });
}

export class ReviewProvider {
  private diagnostics: vscode.DiagnosticCollection;
  private statusBar: StatusBar;
  private reviewing = false;

  constructor(diagnostics: vscode.DiagnosticCollection, statusBar: StatusBar) {
    this.diagnostics = diagnostics;
    this.statusBar = statusBar;
  }

  async reviewCurrentFile(): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
      vscode.window.showWarningMessage("No active file to review.");
      return;
    }
    await this.reviewDocument(editor.document);
  }

  async reviewDocument(document: vscode.TextDocument): Promise<void> {
    if (this.reviewing) {
      vscode.window.showWarningMessage("A review is already in progress.");
      return;
    }

    const content = document.getText();
    if (!content.trim()) {
      return;
    }

    const relativePath = vscode.workspace.asRelativePath(document.uri);
    const settings = getReviewSettings();

    let customBlock = "";
    if (settings.customInstructions) {
      customBlock = `\n## Additional Instructions\n${settings.customInstructions}`;
    }

    const userPrompt = `Review this file.

## File: ${relativePath}
## Language: ${document.languageId}

\`\`\`${document.languageId}
${content.substring(0, 30000)}
\`\`\`

Respond with JSON:
{
  "summary": "1-2 sentence assessment",
  "risk_level": "low|medium|high",
  "comments": [
    {
      "path": "${relativePath}",
      "line": 42,
      "body": "Description of the issue and suggested fix",
      "severity": "critical|warning|suggestion|info"
    }
  ]
}

Rules:
- Maximum ${settings.maxComments} comments, prioritized by severity
- \`line\` must be a valid line number in the file
- Review language: ${settings.language}
- Review style: ${settings.style}
- If the code looks good, return empty comments with positive summary
- ONLY output JSON${customBlock}`;

    await this.executeReview(
      [
        { role: "system", content: SYSTEM_PROMPT },
        { role: "user", content: userPrompt },
      ],
      document.uri,
      document
    );
  }

  async reviewSelection(): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.selection.isEmpty) {
      vscode.window.showWarningMessage("Select code to review.");
      return;
    }

    if (this.reviewing) {
      vscode.window.showWarningMessage("A review is already in progress.");
      return;
    }

    const selection = editor.document.getText(editor.selection);
    const relativePath = vscode.workspace.asRelativePath(editor.document.uri);
    const startLine = editor.selection.start.line + 1;
    const settings = getReviewSettings();

    const userPrompt = `Review this code selection.

## File: ${relativePath} (lines ${startLine}-${editor.selection.end.line + 1})
## Language: ${editor.document.languageId}

\`\`\`${editor.document.languageId}
${selection.substring(0, 15000)}
\`\`\`

Respond with JSON:
{
  "summary": "1-2 sentence assessment",
  "risk_level": "low|medium|high",
  "comments": [
    {
      "path": "${relativePath}",
      "line": ${startLine},
      "body": "Description of the issue",
      "severity": "critical|warning|suggestion|info"
    }
  ]
}

Rules:
- Line numbers are relative to the file (starting at ${startLine})
- Maximum ${settings.maxComments} comments
- Review language: ${settings.language}
- ONLY output JSON`;

    await this.executeReview(
      [
        { role: "system", content: SYSTEM_PROMPT },
        { role: "user", content: userPrompt },
      ],
      editor.document.uri,
      editor.document
    );
  }

  async reviewUncommittedChanges(): Promise<void> {
    if (this.reviewing) {
      vscode.window.showWarningMessage("A review is already in progress.");
      return;
    }

    const workspaceFolders = vscode.workspace.workspaceFolders;
    if (!workspaceFolders) {
      vscode.window.showWarningMessage("No workspace folder open.");
      return;
    }

    const cwd = workspaceFolders[0].uri.fsPath;

    let diff: string;
    try {
      diff = await getGitDiff(cwd);
    } catch (e) {
      vscode.window.showErrorMessage(`Failed to get git diff: ${e}`);
      return;
    }

    if (!diff.trim()) {
      vscode.window.showInformationMessage("No uncommitted changes to review.");
      return;
    }

    const settings = getReviewSettings();

    const userPrompt = `Review these uncommitted changes.

## Diff
\`\`\`diff
${diff.substring(0, 30000)}
\`\`\`

Respond with JSON:
{
  "summary": "1-2 sentence assessment",
  "risk_level": "low|medium|high",
  "comments": [
    {
      "path": "file/path.py",
      "line": 42,
      "body": "Description of the issue",
      "severity": "critical|warning|suggestion|info"
    }
  ]
}

Rules:
- \`line\` must be from the RIGHT side (new code) of the diff
- Maximum ${settings.maxComments} comments, prioritized by severity
- Review language: ${settings.language}
- Review style: ${settings.style}
- ONLY output JSON`;

    // For diff reviews, show results in output channel instead of single file diagnostics
    this.reviewing = true;
    this.statusBar.setReviewing();

    try {
      const config = getConfig();
      const response = await chatCompletion(config, [
        { role: "system", content: SYSTEM_PROMPT },
        { role: "user", content: userPrompt },
      ], { temperature: 0.1, maxTokens: 4096, jsonMode: true });

      const result = parseReviewResponse(response.content);
      result.costUsd = response.costUsd;
      result.model = response.model;

      // Map comments to diagnostics by file
      const diagMap = new Map<string, vscode.Diagnostic[]>();

      for (const comment of result.comments) {
        const filePath = comment.path;
        const uri = vscode.Uri.joinPath(workspaceFolders[0].uri, filePath);
        const line = Math.max(0, comment.line - 1);
        const range = new vscode.Range(line, 0, line, 1000);
        const diag = new vscode.Diagnostic(
          range,
          comment.body,
          severityToDiagnosticSeverity(comment.severity)
        );
        diag.source = "AI Code Reviewer";

        const key = uri.toString();
        if (!diagMap.has(key)) {
          diagMap.set(key, []);
        }
        diagMap.get(key)!.push(diag);
      }

      // Apply diagnostics
      this.diagnostics.clear();
      for (const [uriStr, diags] of diagMap) {
        this.diagnostics.set(vscode.Uri.parse(uriStr), diags);
      }

      this.statusBar.setDone(result.comments.length, result.costUsd);
      this.showResultMessage(result);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      this.statusBar.setError(msg);
      vscode.window.showErrorMessage(`AI review failed: ${msg}`);
    } finally {
      this.reviewing = false;
    }
  }

  private async executeReview(
    messages: Array<{ role: string; content: string }>,
    uri: vscode.Uri,
    document: vscode.TextDocument
  ): Promise<void> {
    this.reviewing = true;
    this.statusBar.setReviewing();

    try {
      const config = getConfig();
      const response = await chatCompletion(config, messages, {
        temperature: 0.1,
        maxTokens: 4096,
        jsonMode: config.provider !== "anthropic",
      });

      const result = parseReviewResponse(response.content);
      result.costUsd = response.costUsd;
      result.model = response.model;

      // Map comments to VS Code diagnostics
      const diagnostics: vscode.Diagnostic[] = [];
      for (const comment of result.comments) {
        const line = Math.max(0, comment.line - 1);
        const lineLength =
          line < document.lineCount
            ? document.lineAt(line).text.length
            : 1000;
        const range = new vscode.Range(line, 0, line, lineLength);

        const diag = new vscode.Diagnostic(
          range,
          comment.body,
          severityToDiagnosticSeverity(comment.severity)
        );
        diag.source = "AI Code Reviewer";
        diagnostics.push(diag);
      }

      this.diagnostics.set(uri, diagnostics);
      this.statusBar.setDone(result.comments.length, result.costUsd);
      this.showResultMessage(result);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      this.statusBar.setError(msg);
      vscode.window.showErrorMessage(`AI review failed: ${msg}`);
    } finally {
      this.reviewing = false;
    }
  }

  private showResultMessage(result: ReviewResult): void {
    const riskEmoji =
      result.riskLevel === "high"
        ? "$(error)"
        : result.riskLevel === "medium"
          ? "$(warning)"
          : "$(pass)";

    if (result.comments.length === 0) {
      vscode.window.showInformationMessage(
        `${riskEmoji} AI Review: No issues found. ${result.summary}`
      );
    } else {
      vscode.window.showInformationMessage(
        `${riskEmoji} AI Review: ${result.comments.length} comments (${result.riskLevel} risk, $${result.costUsd.toFixed(4)}). Check the Problems panel.`
      );
    }
  }
}
