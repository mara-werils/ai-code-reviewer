import * as vscode from "vscode";
import { ReviewProvider } from "./reviewer";
import { StatusBar } from "./statusbar";

let diagnosticCollection: vscode.DiagnosticCollection;
let statusBar: StatusBar;

export function activate(context: vscode.ExtensionContext): void {
  diagnosticCollection =
    vscode.languages.createDiagnosticCollection("ai-code-reviewer");
  statusBar = new StatusBar();

  const reviewer = new ReviewProvider(diagnosticCollection, statusBar);

  context.subscriptions.push(
    diagnosticCollection,
    statusBar,

    vscode.commands.registerCommand("aiCodeReviewer.reviewFile", () =>
      reviewer.reviewCurrentFile()
    ),

    vscode.commands.registerCommand("aiCodeReviewer.reviewDiff", () =>
      reviewer.reviewUncommittedChanges()
    ),

    vscode.commands.registerCommand("aiCodeReviewer.reviewSelection", () =>
      reviewer.reviewSelection()
    ),

    vscode.commands.registerCommand("aiCodeReviewer.clearDiagnostics", () => {
      diagnosticCollection.clear();
      vscode.window.showInformationMessage(
        "AI Code Reviewer: All review comments cleared."
      );
    })
  );

  // Auto-review on save (if enabled)
  context.subscriptions.push(
    vscode.workspace.onDidSaveTextDocument((doc) => {
      const config = vscode.workspace.getConfiguration("aiCodeReviewer");
      if (config.get<boolean>("autoReviewOnSave")) {
        reviewer.reviewDocument(doc);
      }
    })
  );
}

export function deactivate(): void {
  diagnosticCollection?.dispose();
  statusBar?.dispose();
}
