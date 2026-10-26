export type MongoCollectionLike = {
    deleteMany(filter: Record<string, unknown>): Promise<unknown>;
};

export type MongoDbLike = {
    collection(name: string): MongoCollectionLike;
};

export type DeletedAuthUser = {
    id: string;
    email?: string | null;
};

function escapeRegex(value: string): string {
    return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export async function deleteAuthAccountResidue(
    db: MongoDbLike,
    user: DeletedAuthUser,
): Promise<void> {
    const email = user.email?.trim().toLowerCase();
    const verificationFilters: Record<string, unknown>[] = [{ value: user.id }];
    if (email) {
        verificationFilters.push({
            identifier: { $regex: escapeRegex(email), $options: 'i' },
        });
    }
    await Promise.all([
        db.collection('twoFactor').deleteMany({ userId: user.id }),
        db.collection('verification').deleteMany({ $or: verificationFilters }),
    ]);
}
