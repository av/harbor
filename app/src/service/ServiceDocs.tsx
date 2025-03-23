import Markdown from "@uiw/react-markdown-preview";
import { HarborService } from "../serviceMetadata";
import { useEffect, useState } from "react";

const docsFiles = import.meta.glob("/src/docs/*", { query: "?raw" });

const transformUrl = (url: string) => {
  if (url.startsWith(".")) {
    return url.replace("./", "/src/docs/");
  }

  return url;
};

const unknownDoc = () => {
  return {
    default: `
### Missing docs entry
  `,
  };
};

const extractIndex = (iri: string) => {
  const parts = iri.split("/");
  return parts[parts.length - 1].split("-")[0];
};

const resolveFile = (service: HarborService) => {
  const serviceDoc = service?.wikiUrl;

  if (!serviceDoc) {
    return () => Promise.resolve(unknownDoc());
  }

  const index = extractIndex(serviceDoc);
  const maybeDoc = Object.keys(docsFiles).find(
    (key) => extractIndex(key) === index
  );

  if (!maybeDoc) {
    return () => Promise.resolve(unknownDoc());
  }

  return docsFiles[maybeDoc];
};

export const ServiceDocs = ({ service }: { service: HarborService }) => {
  const [content, setContent] = useState("");

  useEffect(() => {
    async function loadContent() {
      const loader = resolveFile(service);

      setContent("");
      await loader().then((docModule) => {
        // @ts-expect-error - dynamic import
        setContent(docModule.default);
      });
    }

    loadContent();
  }, [service]);

  return (
    <>
      <Markdown
        source={content}
        className="p-8 rounded"
        urlTransform={transformUrl}
      />
    </>
  );
};
