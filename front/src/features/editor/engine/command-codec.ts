import type { CommandCodec, EditCommandBatch, MappingContext } from './ports';
import { validateBatch } from './canonical';

/** Classic Command classes stay behind this codec and never cross the wire. */
export const commandCodec: CommandCodec = {
  validate(input: unknown): EditCommandBatch {
    return validateBatch(input);
  },
  toClassic(batch: EditCommandBatch, _context: MappingContext): unknown[] {
    return batch.commands.map((command) => ({ classic: false, command }));
  },
};
