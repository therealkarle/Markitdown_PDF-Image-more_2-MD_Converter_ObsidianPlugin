export type MarkdownGenerator = 'gemini' | 'standard';

export interface PluginSettings {
    geminiApiKey: string;
    modelName: string;
    promptOverride: string;
    footerTemplate: string;
    generatorPriority: MarkdownGenerator[];
    useSeparatePluginSettings: boolean;
}

export const DEFAULT_SETTINGS: PluginSettings = {
    geminiApiKey: '',
    modelName: 'gemini-2.0-flash-lite-preview-02-05',
    promptOverride: '',
    footerTemplate: '\n\n---\nConverted on {{date}} using {{model}}',
    generatorPriority: ['gemini', 'standard'],
    useSeparatePluginSettings: false
};