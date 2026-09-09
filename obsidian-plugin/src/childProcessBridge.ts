import { execFile } from 'child_process';

export interface ConversionOptions {
    useMarkitdown: boolean;
    useOcr: boolean;
    useAi: boolean;
    blockPriority: string[];
    ocrPriority: string[];
    aiAutoDetect: boolean;
    aiImprove: boolean;
    geminiApiKey: string;
    azureOcrKey: string;
    azureOcrEndpoint: string;
    azureDocumentIntelligenceKey: string;
    azureDocumentIntelligenceEndpoint: string;
    tesseractLang: string;
    tesseractCmd: string;
    modelName: string;
    promptOverride: string;
}

export class ChildProcessBridge {
    async convertFile(filePath: string, options: ConversionOptions, scriptPath: string): Promise<string> {
        return new Promise((resolve, reject) => {
            execFile(
                'python',
                [scriptPath, filePath, JSON.stringify(options)],
                (error, stdout, stderr) => {
                    if (error) {
                        const details = stderr.trim() || stdout.trim() || error.message;
                        reject(new Error(details));
                        return;
                    }
                    if (stderr) console.warn(`Stderr: ${stderr}`);
                    if (stdout.trimStart().startsWith('Error:')) {
                        reject(new Error(stdout.trim()));
                        return;
                    }
                    resolve(stdout);
                },
            );
        });
    }
}
