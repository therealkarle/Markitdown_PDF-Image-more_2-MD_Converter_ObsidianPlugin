export type MarkdownGenerator = 'standard' | 'gemini' | 'tesseract' | 'azure_ocr' | 'win_ocr';
export type ConversionMode = 'simple' | 'ocr' | 'ai_enhanced';
export type AiMode = 'fallback' | 'enhancement';

export interface PluginSettings {
    // conversion mode
    mode: ConversionMode;
    // AI settings
    geminiApiKey: string;
    modelName: string;
    promptOverride: string;
    aiMode: AiMode;
    // OCR settings
    ocrPriority: MarkdownGenerator[];
    tesseractLang: string;
    azureOcrKey: string;
    azureOcrEndpoint: string;
    // misc
    footerTemplate: string;
    useSeparatePluginSettings: boolean;
}

export const DEFAULT_SETTINGS: PluginSettings = {
    mode: 'simple',
    geminiApiKey: '',
    modelName: 'gemini-2.0-flash-lite-preview-02-05',
    promptOverride: '',
    aiMode: 'fallback',
    ocrPriority: ['tesseract', 'azure_ocr'],
    tesseractLang: 'deu+eng',
    azureOcrKey: '',
    azureOcrEndpoint: '',
    footerTemplate: '\n\n---\nConverted on {{date}} using {{model}}',
    useSeparatePluginSettings: false,
};