import { Plugin, PluginSettingTab, Setting, Notice, App, TFile } from 'obsidian';
import * as fs from 'fs';
import * as path from 'path';
import { ChildProcessBridge, ConversionOptions } from './childProcessBridge';
import { DEFAULT_SETTINGS, MarkdownGenerator, PluginSettings } from './settings';

const SHARED_SETTINGS_FILE = 'markitdown-settings.json';

export default class MarkItDownPlugin extends Plugin {
    declare settings: PluginSettings;
    bridge!: ChildProcessBridge;

    async onload() {
        await this.loadSettings();
        this.bridge = new ChildProcessBridge();
        this.addSettingTab(new MarkItDownSettingTab(this.app, this));
        this.addRibbonIcon('document-operations', 'MarkItDown Pro', (evt: MouseEvent) => {
            new Notice('MarkItDown Pro is ready!');
        });
        this.addCommand({
            id: 'convert-active-file',
            name: 'Convert Active File to Markdown',
            callback: () => this.convertActiveFile()
        });
    }

    onunload() {
        console.log('Unloading MarkItDown Pro');
    }

    async loadSettings() {
        const data = await this.loadData();
        this.settings = { ...DEFAULT_SETTINGS, ...data };
    }

    async saveSettings() {
        await this.saveData(this.settings);
        await this.updateEnvFile();
    }

    async updateEnvFile() {
        try {
            const pluginDir = (this.app.vault.adapter as any).getBasePath() + path.sep + '.obsidian' + path.sep + 'plugins' + path.sep + 'markitdown-pro';
            const envPath = path.join(pluginDir, '.env');
            const envContent = `GEMINI_API_KEY=${this.settings.geminiApiKey}\n`;
            fs.mkdirSync(pluginDir, { recursive: true });
            fs.writeFileSync(envPath, envContent, 'utf8');
            console.log(`.env file updated at ${envPath}`);
        } catch (error) {
            console.error('Failed to update .env file:', error);
            new Notice('Failed to update .env file. Check console for details.');
        }
    }

    async convertActiveFile() {
        const activeFile = this.app.workspace.getActiveFile();
        if (!activeFile) {
            new Notice('No active file to convert.');
            return;
        }

        try {
            new Notice('Converting file...');
            const scriptPath = path.join(__dirname, '..', 'scripts', 'convert.py');

            const conversionOptions: ConversionOptions = {
                apiKey: this.settings.geminiApiKey,
                modelName: this.settings.modelName,
                promptOverride: this.settings.promptOverride,
                generatorPriority: this.settings.generatorPriority,
            };

            const result = await this.bridge.convertFile(
                activeFile.path,
                conversionOptions,
                scriptPath
            );

            const footer = this.settings.footerTemplate
                .replace('{{date}}', new Date().toISOString().split('T')[0])
                .replace('{{model}}', this.settings.modelName);

            const output = result + footer;
            const outputPath = activeFile.path.replace(/\.[^.]+$/, '') + '.md';

            await this.app.vault.create(outputPath, output);
            new Notice('Conversion complete: ' + outputPath);
        } catch (error) {
            console.error('Conversion error:', error);
            new Notice('Conversion failed. Check console for details.');
        }
    }
}

class MarkItDownSettingTab extends PluginSettingTab {
    plugin: MarkItDownPlugin;

    constructor(app: App, plugin: MarkItDownPlugin) {
        super(app, plugin);
        this.plugin = plugin;
    }

    display(): void {
        const { containerEl } = this;
        containerEl.empty();

        containerEl.createEl('h2', { text: 'MarkItDown Pro Settings' });

        new Setting(containerEl)
            .setName('Gemini API Key')
            .setDesc('Enter your Google Gemini API key. This will be saved to a .env file in the plugin folder.')
            .addText(text => text
                .setPlaceholder('Enter your key...')
                .setValue(this.plugin.settings.geminiApiKey)
                .onChange(async (value) => {
                    this.plugin.settings.geminiApiKey = value;
                    await this.plugin.saveSettings();
                }));

        new Setting(containerEl)
            .setName('Model Name')
            .setDesc('Select the Gemini model to use.')
            .addDropdown(dropdown => dropdown
                .addOption('gemini-2.0-flash-lite-preview-02-05', 'Gemini 2.0 Flash-Lite')
                .addOption('gemini-1.5-flash', 'Gemini 1.5 Flash')
                .addOption('gemini-1.5-pro', 'Gemini 1.5 Pro')
                .setValue(this.plugin.settings.modelName)
                .onChange(async (value) => {
                    this.plugin.settings.modelName = value;
                    await this.plugin.saveSettings();
                }));

        new Setting(containerEl)
            .setName('Prompt Override')
            .setDesc('Custom instructions for the conversion.')
            .addTextArea(text => text
                .setPlaceholder('Enter custom instructions...')
                .setValue(this.plugin.settings.promptOverride)
                .onChange(async (value) => {
                    this.plugin.settings.promptOverride = value;
                    await this.plugin.saveSettings();
                }));

        new Setting(containerEl)
            .setName('Footer Template')
            .setDesc('Template for the conversion metadata footer. Use {{date}} and {{model}} as placeholders.')
            .addText(text => text
                .setPlaceholder('Enter footer template...')
                .setValue(this.plugin.settings.footerTemplate)
                .onChange(async (value) => {
                    this.plugin.settings.footerTemplate = value;
                    await this.plugin.saveSettings();
                }));

        new Setting(containerEl)
            .setName('Generator Priority')
            .setDesc('Determines the priority order of markdown generation methods.')
            .addDropdown(dropdown => dropdown
                .addOption('gemini → standard', 'Use Gemini then Standard')
                .addOption('standard → gemini', 'Use Standard then Gemini')
                .addOption('gemini', 'Use Gemini only')
                .addOption('standard', 'Use Standard only')
                .setValue(this.plugin.settings.generatorPriority.join(' → '))
                .onChange(async (value) => {
                    this.plugin.settings.generatorPriority = value.split(' → ') as MarkdownGenerator[];
                    await this.plugin.saveSettings();
                }));

        new Setting(containerEl)
            .setName('Use Separate Plugin Settings')
            .setDesc('When enabled, settings for this plugin are separate from global settings.')
            .addToggle(toggle => toggle
                .setValue(this.plugin.settings.useSeparatePluginSettings)
                .onChange(async (value) => {
                    this.plugin.settings.useSeparatePluginSettings = value;
                    await this.plugin.saveSettings();
                }));
    }
}