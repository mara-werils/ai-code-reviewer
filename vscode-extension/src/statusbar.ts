import * as vscode from "vscode";

export class StatusBar implements vscode.Disposable {
  private item: vscode.StatusBarItem;

  constructor() {
    this.item = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Right,
      100
    );
    this.item.command = "aiCodeReviewer.reviewFile";
    this.setIdle();
    const config = vscode.workspace.getConfiguration("aiCodeReviewer");
    if (config.get<boolean>("showInStatusBar")) {
      this.item.show();
    }
  }

  setIdle(): void {
    this.item.text = "$(eye) AI Review";
    this.item.tooltip = "Click to review current file with AI";
    this.item.backgroundColor = undefined;
  }

  setReviewing(): void {
    this.item.text = "$(loading~spin) Reviewing...";
    this.item.tooltip = "AI review in progress...";
  }

  setDone(commentCount: number, costUsd: number): void {
    this.item.text = `$(eye) ${commentCount} comments`;
    this.item.tooltip = `AI review complete: ${commentCount} comments ($${costUsd.toFixed(4)})`;
    setTimeout(() => this.setIdle(), 10_000);
  }

  setError(message: string): void {
    this.item.text = "$(error) Review failed";
    this.item.tooltip = message;
    this.item.backgroundColor = new vscode.ThemeColor(
      "statusBarItem.errorBackground"
    );
    setTimeout(() => this.setIdle(), 10_000);
  }

  dispose(): void {
    this.item.dispose();
  }
}
