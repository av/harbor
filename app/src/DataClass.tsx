import { useEffect, useState } from "react";

export class DataClass {
    private listeners: (() => void)[] = [];
    private proxy: ReturnType<DataClass["createProxy"]> | null = null;

    use(): this {
        const [, setUpdates] = useState(0);

        if (!this.proxy) {
            this.proxy = this.createProxy();
        }

        useEffect(() => {
            const listener = () => setUpdates((updates) => updates + 1);
            this.addListener(listener);

            return () => {
                this.removeListener(listener);
            };
        }, []);

        return this.proxy!.proxy as this;
    }

    notifyChange() {
        this.listeners.forEach((listener) => listener());
    }

    addListener(listener: () => void) {
        this.listeners.push(listener);
    }

    removeListener(listener: () => void) {
        if (this.listeners.includes(listener)) {
            this.listeners.splice(this.listeners.indexOf(listener), 1);
        }
    }

    mutate() {
        this.notifyChange();
    }

    getMutableFields(): string[] {
        return [];
    }

    createProxy() {
        const mutableFields = new Set(this.getMutableFields());

        return Proxy.revocable(this, {
            get: (target, prop) => {
                const targetProp = prop as keyof typeof target;

                if (typeof prop === "string" && mutableFields.has(prop)) {
                    const targetValue = target[targetProp];

                    if (typeof targetValue === "function") {
                        return (...args: unknown[]) => {
                            const result = targetValue.apply(target, args);

                            if (result instanceof Promise) {
                                return result.then(() => this.notifyChange())
                                    .then(() => result);
                            }

                            this.notifyChange();
                            return result;
                        };
                    }
                }

                return target[targetProp];
            },
        });
    }

    instance(): this {
        return this;
    }
}

export function useDataClass(cls: DataClass) {
    return cls.use();
}
