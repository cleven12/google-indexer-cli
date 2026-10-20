export const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export function die(message: string): never {
  console.error(message);
  process.exit(1);
}

/** Run `fn` over `items` with at most `size` calls in flight; results keep input order. */
export async function pool<T, R>(items: T[], size: number, fn: (item: T) => Promise<R>): Promise<R[]> {
  const out: R[] = new Array(items.length);
  let next = 0;
  const worker = async () => {
    while (next < items.length) {
      const i = next++;
      out[i] = await fn(items[i]);
    }
  };
  await Promise.all(Array.from({ length: Math.min(size, items.length) }, worker));
  return out;
}
