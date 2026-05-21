DECOY_DB = "coinvault_prod"

DECOY_DATA = {
    "users": {
        "columns": ["id", "username", "email", "password_hash", "balance_usd", "totp_secret", "kyc_verified", "created_at"],
        "rows": [
            ["1", "nakamoto_s",    "s.nakamoto@coinvault.io",  "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj/odXaE.rHO", "14823947.22", "JBSWY3DPEHPK3PXP", "1", "2020-01-03 18:15:05"],
            ["2", "vbuterin_eth",  "v.b@coinvault.io",         "$2b$12$8k9fK2mNpLqR0JhT3vWxYeZaD4cB1iS7gH6uV9yX2wE5tQ0nM3oP", "8934201.77",  "KRUGKIDROVUWG2ZA", "1", "2020-06-30 12:44:19"],
            ["3", "hal_finney",    "hfinney@coinvault.io",     "$2b$12$3Xp7rMnKsLwQ8vT1hY4ZaB2cD9eF0gH6iJ5kL8mN1oP4qR7sU0tV", "3219045.88",  "MFRA2YLBMFRWI5BR", "1", "2021-01-10 09:33:41"],
            ["4", "dev99_wc",      "dev99@protonmail.com",     "$2b$12$Yq4zB7cX1dE5fG8hI2jK0lM3nO6pQ9rS2tU5vW8xY1zA4bC7dE0f", "287450.13",   "NBSWY3DPEB3W64TM", "0", "2022-09-17 14:22:08"],
            ["5", "anon_trader_x", "anon8847@yandex.ru",       "$2b$12$Kp1qR4sT7uV0wX3yZ6aB9cD2eF5gH8iJ1kL4mN7oP0qR3sT6uV9w", "1043822.50",  "OBQXG2DPNVQXIZLB", "0", "2023-02-28 03:17:55"],
        ],
    },
    "wallets": {
        "columns": ["id", "user_id", "currency", "address", "balance", "private_key", "created_at"],
        "rows": [
            ["1", "1", "BTC", "1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf6",          "142.83741200", "5HueCGU8rMjxECyDialwujzZB1s8pUq3HknqfHRfBbMhbcM1ZuZ", "2020-01-03 18:15:05"],
            ["2", "1", "ETH", "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",  "4821.049371",  "a8f4d6c2e0b9371f5e2d4c6a8b0f3e1d7c9b2a4e6f8d0c2b4a6e8f0d2c4b6a8", "2020-01-03 18:16:22"],
            ["3", "2", "ETH", "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "12038.771042", "b9e5f7d3c1a2b4e6f8d0c2b4a6e8f0d2c4b6a8e0f2d4c6a8b0e2f4d6c8b0a2e4", "2020-06-30 12:44:19"],
            ["4", "2", "BTC", "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy",          "89.22018400",  "KwDiBf89QgGbjEhKnhXJuH7LrciVrZi3qYjgd9M7rFYJ3BSBJK9a", "2020-06-30 12:45:03"],
            ["5", "3", "BTC", "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2",          "31.07500000",  "KxJRBhcFUUV2N8aN6VHqBSa3xRaGfJpKJtnTWKEVLDvRHrMBZoFY", "2021-01-10 09:34:07"],
            ["6", "5", "BTC", "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq", "10.45231800",  "L1aaGHEBBfGCUTe5Sq5xLDPRXRRPzqM4HYVzBHcPCnpxKwnLBLSD", "2023-02-28 03:18:14"],
        ],
    },
    "api_keys": {
        "columns": ["id", "user_id", "label", "api_key", "api_secret", "permissions", "ip_whitelist", "last_used"],
        "rows": [
            ["1", "1", "trading-bot-main",  "cv_live_xK9mN2pQ7rS4tU1vW8yZ3aB6cD0eF5gH", "3a8f2d7e1b4c6e9f0a2d5e8b1c4f7a0d3e6b9c2f5a8d1e4b7c0f3a6d9e2b5c8f", "trade,withdraw,read", "185.220.101.0/24", "2024-11-14 02:33:17"],
            ["2", "2", "arb-bot-eth",       "cv_live_aB3cD6eF9gH2iJ5kL8mN1oP4qR7sT0u", "f0a3d6e9b2c5f8a1d4e7b0c3f6a9d2e5b8c1f4a7d0e3b6c9f2a5d8e1b4c7f0a3", "trade,read",         None,               "2024-12-01 18:47:52"],
            ["3", "5", "anon-withdraw-key", "cv_live_vW6xX9yY2zA5bB8cC1dD4eE7fF0gG3hH", "1d4e7b0c3f6a9d2e5b8c1f4a7d0e3b6c9f2a5d8e1b4c7f0a3d6e9b2c5f8a1d4e7", "withdraw",           None,               "2025-01-03 00:12:44"],
        ],
    },
    "transactions": {
        "columns": ["id", "from_address", "to_address", "amount", "currency", "tx_hash", "confirmations", "status", "created_at"],
        "rows": [
            ["1", "1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf6",          "3FZbgi29cpjq2GjdwV8eyHuJJnkLtktZc5",       "12.50000000", "BTC", "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2", "6",  "confirmed", "2024-10-22 14:15:33"],
            ["2", "0x742d35Cc6634C0532925a3b844Bc454e4438f44e", "0x3fC91A3afd70395Cd496C647d5a6CC9D4B2b7FAD", "500.000000",  "ETH", "0xd4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5", "64", "confirmed", "2024-11-08 09:27:41"],
            ["3", "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq", "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2",        "2.10000000",  "BTC", "b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3",  "3",  "confirmed", "2025-01-02 22:04:19"],
        ],
    },
    "withdrawals": {
        "columns": ["id", "user_id", "amount", "currency", "destination_address", "fee", "status", "tx_hash", "created_at"],
        "rows": [
            ["1", "5", "8.00000000",  "BTC", "1FeexV6bAHb8ybZjqQMjJrcCrHGW9sb6uF",         "0.00050000", "completed", "c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4", "2025-01-03 00:20:11"],
            ["2", "1", "1000.000000", "ETH", "0x3fC91A3afd70395Cd496C647d5a6CC9D4B2b7FAD",  "0.002100",   "completed", "0xe5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6", "2024-11-09 11:33:07"],
            ["3", "5", "5.50000000",  "BTC", "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh", "0.00050000", "pending",   None,                                                                    "2025-01-02 23:58:42"],
        ],
    },
    "admin_users": {
        "columns": ["id", "username", "email", "role", "password_hash", "last_login", "2fa_enabled"],
        "rows": [
            ["1", "admin",    "admin@coinvault.io", "superadmin", "$2b$12$xR7pT4uV8wY1zA3bC6dE9fG2hI5jK8lM1nO4pQ7rS0tU3vW6xY9z", "2025-01-03 08:41:22", "1"],
            ["2", "ops_lead", "ops@coinvault.io",   "operator",   "$2b$12$aB4cD7eF0gH3iJ6kL9mN2oP5qR8sT1uV4wX7yZ0aB3cD6eF9gH2i", "2024-12-28 14:17:03", "1"],
        ],
    },
}
