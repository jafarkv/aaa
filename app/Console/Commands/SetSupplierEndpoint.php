<?php

namespace App\Console\Commands;

use App\Models\Supplier;
use App\Models\SupplierEndpoint;
use App\PromoStandards\Service;
use Illuminate\Console\Command;

class SetSupplierEndpoint extends Command
{
    protected $signature = 'hub:supplier:endpoint
        {slug : Supplier slug}
        {service : Service name, e.g. product_data, inventory, media, ppc, purchase_order}
        {url : Full HTTPS URL of the supplier\'s SOAP endpoint}
        {--ws-version= : Service version (defaults to the standard version for that service)}
        {--disable : Keep the endpoint but exclude it from tests and syncs}';

    protected $description = 'Add or update one supplier endpoint by hand (for suppliers missing from the directory)';

    public function handle(): int
    {
        $supplier = Supplier::where('slug', $this->argument('slug'))->first();
        if (! $supplier) {
            $this->error('Unknown supplier slug.');

            return self::FAILURE;
        }

        $input = (string) $this->argument('service');
        $service = Service::tryFrom($input) ?? Service::fromDirectoryName($input);
        if (! $service) {
            $this->error("Unknown service '{$input}'. Use one of: ".implode(', ', array_column(Service::cases(), 'value')));

            return self::FAILURE;
        }

        $url = (string) $this->argument('url');
        // Credentials travel inside the SOAP body, so plain HTTP would expose them.
        if (! str_starts_with(strtolower($url), 'https://') || filter_var($url, FILTER_VALIDATE_URL) === false) {
            $this->error('The endpoint must be a valid https:// URL.');

            return self::FAILURE;
        }

        $version = $this->option('ws-version') ?: $service->defaultVersion();

        // source=manual makes this endpoint immune to directory re-imports.
        $supplier->endpoints()->updateOrCreate(
            ['service' => $service->value, 'version' => $version],
            ['url' => $url, 'source' => SupplierEndpoint::SOURCE_MANUAL, 'is_enabled' => ! $this->option('disable')],
        );

        $this->info("{$service->label()} {$version} set for {$supplier->slug}.");

        return self::SUCCESS;
    }
}
