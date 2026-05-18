'use strict';
const vscode = require('vscode');
const { ForgeWebviewProvider } = require('./provider');

function activate(context) {
  const provider = new ForgeWebviewProvider(context.extensionUri);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(ForgeWebviewProvider.viewType, provider)
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('forge.refresh', () => provider.refresh())
  );
}

function deactivate() {}

module.exports = { activate, deactivate };
