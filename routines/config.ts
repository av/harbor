export class ConfigValueParser<T> {
  parse(value: string): T {
    throw new Error("Method not implemented.");
  }

  serialize(value: T): string {
    throw new Error("Method not implemented.");
  }
}

export class StringParser extends ConfigValueParser<string> {
  override parse(value: string): string {
    return value;
  }

  override serialize(value: string): string {
    return value;
  }
}

export class StringListParser extends ConfigValueParser<string[]> {
  separator = ';';

  override parse(value: string): string[] {
    return value.split(this.separator).map((v) => v.trim());
  }

  override serialize(value: string[]): string {
    return value.join(this.separator);
  }
}

export class ConfigValue<ParsedType = string> {
  key: string;
  parser: ConfigValueParser<ParsedType>;

  rawValue: string | undefined;
  parsedValue: ParsedType | undefined;

  constructor({
    key,
    parser,
  }: {
    key: string;
    parser?: ConfigValueParser<ParsedType>;
  }) {
    this.key = key;

    if (parser === undefined) {
      this.parser = new StringParser() as ConfigValueParser<ParsedType>;
    } else {
      if (parser instanceof ConfigValueParser) {
        this.parser = parser;
      } else {
        const ParserClass = parser as new () => ConfigValueParser<ParsedType>;
        this.parser = new ParserClass();
      }
    }
  }

  async resolve(): Promise<void> {
    throw new Error("Method not implemented.");
  }

  get value(): ParsedType | undefined {
    if (this.parsedValue === undefined && this.rawValue !== undefined) {
      this.parsedValue = this.parser.parse(this.rawValue);
    }

    return this.parsedValue;
  }

  set value(value: ParsedType | undefined) {
    this.parsedValue = value;
    this.rawValue = value !== undefined ? this.parser.serialize(value) : undefined;
  }

  async unwrap(): Promise<ParsedType | undefined> {
    if (this.rawValue === undefined) {
      await this.resolve();
    }

    return this.value;
  }
}
