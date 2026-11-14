<?php

namespace App\PromoStandards;

/**
 * Builds PromoStandards SOAP 1.1 requests as plain XML over HTTP. No ext-soap needed, and
 * the request is a string, so it is trivial to fake in tests.
 *
 * VERIFY: element layout (credentials in the SharedObjects namespace, parameters in the
 * service namespace) follows the common PromoStandards shape but is unchecked against WSDLs.
 */
class SoapEnvelope
{
    /** @param array<string, string> $params */
    public static function build(
        Service $service,
        string $version,
        string $method,
        string $username,
        string $password,
        array $params = [],
    ): string {
        $ns = $service->namespace($version);
        $shared = $ns.'SharedObjects/';

        $body = '';
        foreach ($params as $name => $value) {
            $body .= "<ns:{$name}>".self::esc($value)."</ns:{$name}>";
        }

        $request = ucfirst($method).'Request';

        return '<?xml version="1.0" encoding="UTF-8"?>'
            .'<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"'
            .' xmlns:ns="'.self::esc($ns).'" xmlns:shar="'.self::esc($shared).'">'
            .'<soapenv:Body>'
            ."<ns:{$request}>"
            .'<shar:wsVersion>'.self::esc($version).'</shar:wsVersion>'
            .'<shar:id>'.self::esc($username).'</shar:id>'
            .'<shar:password>'.self::esc($password).'</shar:password>'
            .$body
            ."</ns:{$request}>"
            .'</soapenv:Body></soapenv:Envelope>';
    }

    /**
     * Hash identifying a request WITHOUT its credentials, safe to store and compare.
     *
     * @param  array<string, string>  $params
     */
    public static function requestHash(Service $service, string $version, string $method, array $params): string
    {
        ksort($params);

        return hash('sha256', json_encode([$service->value, $version, $method, $params]));
    }

    private static function esc(string $value): string
    {
        return htmlspecialchars($value, ENT_XML1 | ENT_QUOTES, 'UTF-8');
    }
}
