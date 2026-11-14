<?php

namespace App\PromoStandards;

use DOMDocument;
use DOMXPath;

/** Parsed supplier response: did it succeed, and what did the supplier say if not. */
class SoapResult
{
    /**
     * @param  list<string>  $errors
     * @param  list<string>  $productIds
     */
    private function __construct(
        public readonly bool $ok,
        public readonly array $errors,
        public readonly array $productIds,
    ) {}

    public static function parse(?string $xml): self
    {
        if ($xml === null || trim($xml) === '') {
            return new self(false, ['Empty response from supplier'], []);
        }

        $doc = new DOMDocument;
        $previous = libxml_use_internal_errors(true);
        // LIBXML_NONET: never fetch external entities or DTDs named by a supplier response.
        $loaded = $doc->loadXML($xml, LIBXML_NONET);
        libxml_clear_errors();
        libxml_use_internal_errors($previous);

        if (! $loaded) {
            return new self(false, ['Response was not valid XML'], []);
        }

        $xp = new DOMXPath($doc);
        $errors = [];

        foreach ($xp->query("//*[local-name()='Fault']") as $fault) {
            $text = $xp->evaluate("string(*[local-name()='faultstring'])", $fault);
            $errors[] = 'SOAP fault: '.($text !== '' ? $text : 'unspecified');
        }

        // PromoStandards reports business errors as ServiceMessage elements, usually with HTTP 200.
        foreach ($xp->query("//*[local-name()='ServiceMessage']") as $message) {
            $severity = strtolower($xp->evaluate("string(*[local-name()='severity'])", $message));
            if ($severity === 'error') {
                $code = $xp->evaluate("string(*[local-name()='code'])", $message);
                $desc = $xp->evaluate("string(*[local-name()='description'])", $message);
                $errors[] = trim("Supplier error {$code}: {$desc}", ': ');
            }
        }

        $ids = [];
        foreach ($xp->query("//*[translate(local-name(),'PRODUCTID','productid')='productid']") as $node) {
            $value = trim($node->textContent);
            if ($value !== '') {
                $ids[$value] = true;
            }
        }

        return new self($errors === [], $errors, array_map('strval', array_keys($ids)));
    }
}
