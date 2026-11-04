import { getWhatToBelieve } from '@/lib/research/what-to-believe';
import { WhatToBelieveView } from './WhatToBelieveView';

export async function WhatToBelieveSection({ ticker }: { ticker: string }) {
    const data = await getWhatToBelieve(ticker);
    return <WhatToBelieveView data={data} />;
}
