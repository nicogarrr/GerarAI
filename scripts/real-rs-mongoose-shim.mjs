// Shim ESM sobre mongoose (CJS) para node --experimental-strip-types.
import pkg from 'mongoose';
export default pkg;
export const Schema = pkg.Schema;
export const model = pkg.model;
export const models = pkg.models;
export const connect = pkg.connect;
export const connection = pkg.connection;
export const startSession = pkg.startSession.bind(pkg);
