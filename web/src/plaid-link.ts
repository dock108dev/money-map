interface PlaidLinkMetadata {
  institution?: { institution_id?: string; name?: string };
}

interface PlaidLinkError {
  error_code?: string;
  display_message?: string;
  error_message?: string;
}

interface PlaidHandler {
  open(): void;
  destroy(): void;
}

interface PlaidFactory {
  create(options: {
    token: string;
    onSuccess(publicToken: string, metadata: PlaidLinkMetadata): void;
    onExit(error: PlaidLinkError | null): void;
  }): PlaidHandler;
}

declare global {
  interface Window {
    Plaid?: PlaidFactory;
  }
}

let loader: Promise<PlaidFactory> | null = null;

function loadPlaid(): Promise<PlaidFactory> {
  if (window.Plaid) return Promise.resolve(window.Plaid);
  if (loader) return loader;
  loader = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://cdn.plaid.com/link/v2/stable/link-initialize.js";
    script.async = true;
    script.onload = () => {
      if (window.Plaid) resolve(window.Plaid);
      else reject(new Error("Plaid Link loaded without becoming available."));
    };
    script.onerror = () => reject(new Error("Plaid Link could not be loaded."));
    document.head.append(script);
  });
  return loader;
}

export async function openPlaidLink(
  linkToken: string,
  onSuccess: (publicToken: string) => Promise<void>,
): Promise<void> {
  const plaid = await loadPlaid();
  await new Promise<void>((resolve, reject) => {
    const handler = plaid.create({
      token: linkToken,
      onSuccess: (publicToken) => {
        void onSuccess(publicToken)
          .then(() => {
            handler.destroy();
            resolve();
          })
          .catch((error: unknown) => {
            handler.destroy();
            reject(error instanceof Error ? error : new Error("Plaid exchange failed."));
          });
      },
      onExit: (error) => {
        handler.destroy();
        if (error) {
          reject(
            new Error(
              error.display_message ??
                error.error_message ??
                `Plaid Link exited (${error.error_code ?? "unknown error"}).`,
            ),
          );
        } else {
          resolve();
        }
      },
    });
    handler.open();
  });
}
